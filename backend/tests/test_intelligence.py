"""Pipeline tests use real decoding/PDF creation and mocked expensive OCR inference."""
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pypdf import PdfReader
from sqlalchemy import func, select
from support import client, new_account
from app.database import SessionLocal
from app.models import OCRResult, ExtractedField, AuditLog
from app.services.compliance import evaluate_rules
from app.services.extraction import extract_fields
from app.services.image_processing import prepare_image, ImageError
from app.services.ocr import OCRUnavailable, ocr_service
from scripts.seed_demo_rules import seed_rules

FIXTURE = Path(__file__).parent / 'fixtures' / 'package_front.png'
BOX = [[.1,.1],[.8,.1],[.8,.2],[.1,.2]]

def region(text='MRP Rs. 120/-', confidence=.99):
    return {'text':text,'confidence':confidence,'bounding_box':BOX}

def image(text='MRP Rs. 120/-', **kw):
    return {'image_id':str(uuid4()),'image_side':'front','status':'success','quality':'GOOD','texts':[region(text)],**kw}

def rule(**kw):
    data=dict(id=str(uuid4()),rule_code='TEST',title='Test check',description='Test only',product_category=None,
        field_name='mrp',validator_type='numeric',validator_config={'min':1},severity='warning',source_document='TEST ONLY',
        source_reference=None,effective_from=date(2020,1,1),effective_to=None,version=1,is_active=True,is_demo_or_provisional=False)
    return SimpleNamespace(**(data|kw))

@pytest.fixture(scope='module')
def accounts():
    with SessionLocal() as db: seed_rules(db)
    return new_account(),new_account(),new_account('admin')

@pytest.fixture
def inference(monkeypatch):
    calls=[]
    def recognize(*args):
        calls.append(args)
        return [region()]
    monkeypatch.setattr(ocr_service,'recognize',recognize)
    return calls

def inspection(account, sides=('front',), corrupt=False):
    headers=account['headers']
    response=client.post('/inspections',headers=headers)
    assert response.status_code==201,response.text
    ident=response.json()['inspection_id']
    for side in sides:
        response=client.post(f'/inspections/{ident}/images',headers=headers,data={'image_side':side},
            files={'file':('test.png',b'corrupt' if corrupt and side==sides[-1] else FIXTURE.read_bytes(),'image/png')})
        assert response.status_code==201,response.text
    return '/inspections/'+ident

@pytest.mark.parametrize('text,name,value',[
    ('MRP Rs. 120/-','mrp',120),('Net Wt. 500 g','net_quantity',500),
    ('Manufactured by: Example Foods','manufacturer_or_packer','Example Foods'),
    ('Consumer Care: 18001234567','consumer_care_phone','18001234567'),
    ('Email: care@example.com','consumer_care_email','care@example.com'),
    ('Mfg Date: 01/08/2026','manufacturing_or_packing_date','2026-08-01'),
    ('Best Before: 01/08/2027','best_before_or_use_by','2027-08-01'),
    ('Brand: Example','brand_name','Example'),('Product: Rice','product_name','Rice'),
    ('Country of Origin: India','country_of_origin','India'),
    ('Imported by: Sample Ltd','importer','Sample Ltd'),
    ('Unit Sale Price: Rs. 240 per kg','unit_sale_price',240)])
def test_extraction(text,name,value):
    fields=extract_fields([image(text)])
    found=next(field for field in fields if field['field_name']==name)
    assert found['normalized_value']['value']==value
    assert found['source_text']==text and found['bounding_box']==BOX
    assert 0 < found['confidence'] <= .99

def test_no_invented_manufacturer():
    assert not extract_fields([image('Marketed by: Someone')])

def test_address_context():
    data=image('Manufactured by: Example')
    data['texts'].append({'text':'Address: Pune','confidence':.98,'bounding_box':[[.1,.3],[.8,.3],[.8,.4],[.1,.4]]})
    assert any(f['field_name']=='manufacturer_address' for f in extract_fields([data]))

@pytest.mark.parametrize('value,status,overall',[(120,'PASS','COMPLIANT'),(0,'FAIL','NON_COMPLIANT')])
def test_rule_numeric(value,status,overall):
    imgs=[image(f'MRP Rs. {value}')]
    evaluations,result=evaluate_rules([rule()],extract_fields(imgs),imgs)
    assert evaluations[0]['status']==status and result==overall

@pytest.mark.parametrize('change',[{'quality':'LOW_QUALITY'},{'texts':[region(confidence=.3)]},{'status':'failed','texts':[]}])
def test_uncertainty_reviews(change):
    imgs=[image(**change)]
    evaluations,result=evaluate_rules([rule()],extract_fields(imgs),imgs)
    assert evaluations[0]['status']=='REVIEW' and result=='REVIEW_REQUIRED'

@pytest.mark.parametrize('changes',[{'is_active':False},{'effective_from':date.today()+timedelta(days=1)},{'effective_to':date.today()-timedelta(days=1)}])
def test_rule_filtering(changes):
    assert evaluate_rules([rule(**changes)],[],[image()])==([], 'REVIEW_REQUIRED')

def test_provisional_never_certifies():
    imgs=[image()]
    results,overall=evaluate_rules([rule(is_demo_or_provisional=True)],extract_fields(imgs),imgs)
    assert results[0]['status']=='PASS' and overall=='REVIEW_REQUIRED'

def test_absence_requires_configured_coverage():
    imgs=[image('Unrelated text'),image('Other text',image_side='back')]
    results,_=evaluate_rules([rule(validator_type='required',validator_config={'absence_is_failure':True})],[],imgs)
    assert results[0]['status']=='FAIL'
    assert evaluate_rules([rule()],[],imgs)[0][0]['status']=='REVIEW'

def test_unsupported_category_and_conflict():
    imgs=[image(),image('MRP Rs. 300',image_side='back')]
    fields=extract_fields(imgs)
    assert evaluate_rules([rule()],fields,imgs)[0][0]['status']=='REVIEW'
    assert evaluate_rules([rule()],fields[:1],imgs,category='unverified-category')[0][0]['status']=='REVIEW'

def test_preprocessing_preserves_original(tmp_path):
    before=FIXTURE.read_bytes()
    result=prepare_image(FIXTURE,tmp_path/'derived')
    assert result['evidence_path'].is_file() and result['ocr_path'].is_file()
    assert FIXTURE.read_bytes()==before
    assert result['metrics']['heuristic'] is True

def test_corrupt_decode(tmp_path):
    path=tmp_path/'broken.png';path.write_bytes(b'not png')
    with pytest.raises(ImageError): prepare_image(path,tmp_path/'derived')

@pytest.mark.parametrize('sides',[('front',),('front','back')])
def test_ocr_persistence_cache_and_force(accounts,inference,sides):
    owner=accounts[0]; base=inspection(owner,sides)
    response=client.post(base+'/ocr',headers=owner['headers'])
    assert response.status_code==200,response.text
    assert response.json()['successful_images']==len(sides)
    assert len(inference)==len(sides)
    assert client.post(base+'/ocr',headers=owner['headers']).json()['images'][0]['cached']
    assert len(inference)==len(sides)
    client.post(base+'/ocr?force=true',headers=owner['headers'])
    assert len(inference)==2*len(sides)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(OCRResult).where(OCRResult.inspection_id==base.split('/')[-1]))==len(sides)

def test_partial_failure(accounts,inference):
    owner=accounts[0];base=inspection(owner,('front','back'),corrupt=True)
    response=client.post(base+'/analyze',headers=owner['headers'])
    assert response.status_code==200,response.text
    result=response.json()
    assert result['ocr_summary']['partial_success'] and result['overall_status']=='REVIEW_REQUIRED'
    assert len(result['declarations'])==1
    assert result['images'][1]['status']=='failed'

def test_model_unavailable(accounts,monkeypatch):
    def unavailable(*args): raise OCRUnavailable('OCR unavailable; retry later.')
    monkeypatch.setattr(ocr_service,'recognize',unavailable)
    owner=accounts[0];base=inspection(owner)
    response=client.post(base+'/analyze',headers=owner['headers'])
    assert response.status_code==200,response.text
    assert response.json()['ocr_summary']['failed_images']==1
    assert response.json()['overall_status']=='REVIEW_REQUIRED'
    assert 'OCR could not read any package images' in response.json()['availability_message']
    assert client.get(base+'/result',headers=owner['headers']).status_code==200

def test_persisted_result_accessible_while_ocr_unavailable(accounts,inference,monkeypatch):
    owner=accounts[0];base=inspection(owner)
    original=client.post(base+'/analyze',headers=owner['headers']).json()
    calls=len(inference)
    def unavailable(*args): raise OCRUnavailable('OCR is temporarily unavailable.')
    monkeypatch.setattr(ocr_service,'recognize',unavailable)
    saved=client.get(base+'/result',headers=owner['headers'])
    assert saved.status_code==200 and saved.json()['analysis_id']==original['analysis_id']
    reused=client.post(base+'/analyze',headers=owner['headers']).json()
    assert reused['analysis_id']==original['analysis_id'] and reused['reused_analysis'] is True
    assert len(inference)==calls

def test_admin_ocr_warmup(accounts,monkeypatch):
    owner,_,admin=accounts
    assert client.post('/admin/ocr/warmup',headers=owner['headers']).status_code==403
    monkeypatch.setattr(ocr_service,'warmup',lambda:{'status':'ONLINE','state':'READY','detail':'Ready.',
                                                    'initialization_duration_seconds':1.25})
    warmed=client.post('/admin/ocr/warmup',headers=admin['headers'])
    assert warmed.status_code==200 and warmed.json()['state']=='READY'

@pytest.mark.parametrize('endpoint',['ocr','analyze','report'])
def test_analysis_authorization(accounts,endpoint):
    owner,other,_=accounts;base=inspection(owner,())
    assert client.post(base+'/'+endpoint).status_code==401
    assert client.post(base+'/'+endpoint,headers=other['headers']).status_code==403
    if endpoint!='report': assert client.post(base+'/'+endpoint,headers=owner['headers']).status_code==422

def test_report_evidence_persistence_and_audit(accounts,inference):
    owner,other,admin=accounts;base=inspection(owner,('front','back'))
    response=client.post(base+'/analyze',headers=owner['headers'])
    assert response.status_code==200,response.text
    result=response.json()
    persisted=client.get(base+'/result',headers=owner['headers'])
    assert persisted.json()['analysis_id']==result['analysis_id'] and not persisted.json()['stale']
    evidence=base+'/images/'+result['images'][0]['image_id']+'/evidence'
    assert client.get(evidence,headers=owner['headers']).headers['content-type']=='image/png'
    assert client.get(evidence,headers=other['headers']).status_code==403
    created=client.post(base+'/report',headers=owner['headers'])
    assert created.status_code==201,created.text
    own_reports=client.get('/inspections/reports',headers=owner['headers']).json()
    assert own_reports[0]['inspection_id']==base.split('/')[-1]
    assert own_reports[0]['creator_id']==owner['id'] and own_reports[0]['creator_name']=='Test User'
    assert client.get('/inspections/reports',headers=other['headers']).json()==[]
    admin_reports=client.get('/admin/reports',headers=admin['headers']).json()
    assert any(item['report_id']==created.json()['report_id'] for item in admin_reports)
    summary=client.get('/inspections/summary',headers=owner['headers']).json()
    assert summary['reports_generated']==1 and summary['recent'][0]['reports_generated']==1
    pdf=client.get(base+'/report',headers=owner['headers'])
    assert pdf.status_code==200,pdf.text[:100]
    exact_pdf=client.get(f"{base}/reports/{created.json()['report_id']}",headers=owner['headers'])
    assert exact_pdf.status_code==200 and exact_pdf.headers['content-type']=='application/pdf'
    assert client.get(f"{base}/reports/{created.json()['report_id']}",headers=other['headers']).status_code==403
    reader=PdfReader(BytesIO(pdf.content));text='\n'.join(p.extract_text() for p in reader.pages)
    assert 'PackSure AI' in text and 'PROVISIONAL' in text and '120' in text
    assert client.get(base+'/report',headers=other['headers']).status_code==403
    assert client.get(base+'/report',headers=admin['headers']).status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExtractedField).where(ExtractedField.analysis_id==result['analysis_id']))==2
        actions=set(db.scalars(select(AuditLog.action).where(AuditLog.resource_id==base.split('/')[-1])))
        assert {'ocr.started','ocr.completed','analysis.completed','report.created','report.viewed'} <= actions
    client.post(base+'/images',headers=owner['headers'],data={'image_side':'left'},files={'file':('x.png',FIXTURE.read_bytes(),'image/png')})
    assert client.get(base+'/result',headers=owner['headers']).json()['stale']
    assert client.get(base+'/report',headers=owner['headers']).status_code==409

def test_admin_rules(accounts):
    owner,_,admin=accounts
    assert client.get('/admin/rules',headers=owner['headers']).status_code==403
    rules=client.get('/admin/rules',headers=admin['headers']).json()
    assert len(rules)==5 and all(r['is_demo_or_provisional'] for r in rules)
    path='/admin/rules/'+rules[0]['id']
    assert client.patch(path,headers=admin['headers'],json={'is_active':False}).json()['is_active'] is False
    assert client.patch(path,headers=admin['headers'],json={'is_active':True,'validator_config':{'code':'unsafe'}}).status_code==422
    assert client.patch(path,headers=admin['headers'],json={'is_active':True}).status_code==200


def test_correction_persistence_permissions_audit_and_reevaluation(accounts,inference):
    owner,other,admin=accounts
    base=inspection(owner)
    analyzed=client.post(base+'/analyze',headers=owner['headers'])
    assert analyzed.status_code==200,analyzed.text
    field=next(item for item in analyzed.json()['declarations'] if item['field_name']=='mrp')
    endpoint=f"{base}/fields/{field['id']}"
    ocr_calls=len(inference)
    assert client.post(base+'/report',headers=owner['headers']).status_code==201

    assert client.patch(endpoint,json={'corrected_value':'0'}).status_code==401
    assert client.patch(endpoint,headers=other['headers'],json={'corrected_value':'0'}).status_code==403
    corrected=client.patch(endpoint,headers=owner['headers'],json={'corrected_value':'0'})
    assert corrected.status_code==200,corrected.text
    assert len(inference)==ocr_calls  # A correction reevaluates rules without OCR.

    result=corrected.json()
    saved=next(item for item in result['declarations'] if item['id']==field['id'])
    assert saved['machine_value']['value']==120
    assert saved['corrected_value']['value']==0
    assert saved['normalized_value']['value']==0
    assert saved['human_reviewed'] is True
    assert saved['corrected_by']==owner['id'] and saved['corrected_at']
    assert result['report_ready'] is False
    assert client.get(base+'/report',headers=owner['headers']).status_code==404
    mrp_rule=next(item for item in result['rule_evaluations'] if item['field_name']=='mrp')
    assert mrp_rule['status']=='FAIL'
    assert mrp_rule['reason'].startswith('Human-corrected')

    persisted=client.get(base+'/result',headers=owner['headers']).json()
    persisted_field=next(item for item in persisted['declarations'] if item['id']==field['id'])
    assert persisted_field['corrected_value']['value']==0 and persisted_field['human_reviewed']
    assert client.get(base+'/result',headers=other['headers']).status_code==403
    assert client.get(base+'/result',headers=admin['headers']).status_code==200

    admin_update=client.patch(endpoint,headers=admin['headers'],json={'corrected_value':'INR 130'})
    assert admin_update.status_code==200,admin_update.text
    admin_field=next(item for item in admin_update.json()['declarations'] if item['id']==field['id'])
    assert admin_field['machine_value']['value']==120 and admin_field['corrected_value']['value']==130
    assert admin_field['corrected_by']==admin['id'] and len(inference)==ocr_calls
    assert client.post(base+'/report',headers=admin['headers']).status_code==201
    report=client.get(base+'/report',headers=admin['headers'])
    report_text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(report.content)).pages)
    assert 'Machine extracted' in report_text and 'Human corrected' in report_text and 'INR 130' in report_text

    with SessionLocal() as db:
        stored=db.get(ExtractedField,field['id'])
        assert stored.machine_value['value']==120 and stored.corrected_value['value']==130
        events=db.scalars(select(AuditLog).where(AuditLog.action=='field.corrected',
                         AuditLog.resource_id==base.split('/')[-1])).all()
        assert len(events)==2
        assert all(event.details['field_id']==field['id'] and event.details['rules_reevaluated'] for event in events)


@pytest.mark.parametrize('value',["", "not a number"])
def test_correction_validation(accounts,inference,value):
    owner=accounts[0];base=inspection(owner)
    result=client.post(base+'/analyze',headers=owner['headers']).json()
    field=next(item for item in result['declarations'] if item['field_name']=='mrp')
    response=client.patch(f"{base}/fields/{field['id']}",headers=owner['headers'],json={'corrected_value':value})
    assert response.status_code==422
