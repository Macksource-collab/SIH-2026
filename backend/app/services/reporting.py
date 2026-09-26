"""ReportLab reports of immutable analysis snapshots; no official legal claims."""
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

DISCLAIMER = "PackSure AI assists inspection by extracting package information and evaluating configured rules. Low-confidence or ambiguous results require human verification."


def generate_pdf(path, snapshot, inspector_name, timestamp):
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallText",fontName="Helvetica",fontSize=8,leading=11,spaceAfter=4))
    styles.add(ParagraphStyle(name="BrandTitle",parent=styles["Title"],textColor=colors.HexColor("#1d4ed8"),fontSize=22,leading=26,spaceAfter=4))
    styles["BodyText"].fontSize=9
    styles["BodyText"].leading=13
    def p(value,style="BodyText"):
        # OCR text is untrusted, including ReportLab markup.
        text=str(value).replace("₹","INR ")
        return Paragraph(escape(text).replace("\n","<br/>"),styles[style])
    provisional=any(rule.get("verification_status","DEMO" if rule.get("is_demo_or_provisional",True) else "VERIFIED") != "VERIFIED" for rule in snapshot["rule_evaluations"])
    inspection=snapshot["inspection"]
    story=[p("PackSure AI","BrandTitle"),p("Package Inspection Assistance Report","Heading2"),
           p("Inspection ID: "+snapshot["inspection"]["inspection_id"]),p("Inspector: "+inspector_name),
           p("Analysis: "+snapshot["analysis_id"]),p("Report created (UTC): "+timestamp),
           p("Overall: "+snapshot["overall_status"].replace("_"," "),"Heading2"),
           p(snapshot["notice"],"Heading3"),p(DISCLAIMER),Spacer(1,5*mm),p("Product information","Heading2")]
    def table(headers, rows, widths):
        data=[[p(item,"SmallText") for item in headers]]+[[p(item,"SmallText") for item in row] for row in rows]
        t=Table(data,colWidths=widths,repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#dbeafe")),
                              ("VALIGN",(0,0),(-1,-1),"TOP"),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#cbd5e1")),
                              ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                              ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        story.append(t)
    table(["Product name","Category","Inspection created","Last updated"],
          [[inspection.get("product_name") or "Not detected / not supplied",inspection.get("product_category") or "Not supplied",
            inspection.get("created_at") or "Not available",inspection.get("updated_at") or "Not available"]],[145,110,120,120])
    story.append(p("Submitted images and quality","Heading2"))
    table(["Side","Quality","OCR / observations"],[(image["image_side"],image["quality"],
          image.get("error") or f"{len(image['texts'])} text regions. "+" ".join(image["metrics"].get("notes",[]))) for image in snapshot["images"]],[65,95,335])
    story.append(p("Detected declarations","Heading2"))
    fields=snapshot["declarations"]
    table(["Declaration","Machine extracted","Human corrected","Confidence / side"],
          [(field["field_name"].replace("_"," "),field.get("machine_value",field["normalized_value"]).get("display",""),
            field.get("corrected_value",{}).get("display","Not corrected") if field.get("corrected_value") else "Not corrected",
            ("Human reviewed" if field.get("human_reviewed") else f"{field['confidence']:.0%}")+f" / {field['image_side']}")
           for field in fields] or [["None","No reliable evidence detected","Not corrected","Manual review"]],[110,145,150,90])
    story.append(p("Configured rule evaluations"+(" - DEMO / PROVISIONAL" if provisional else ""),"Heading2"))
    for rule in snapshot["rule_evaluations"]:
        story.append(KeepTogether([p(f"{rule['rule_code']}: {rule['title']} - {rule['status']}","Heading3"),
                                  p("Severity: "+rule["severity"]+" | Version: "+str(rule["version"])+
                                    " | Verification: "+rule.get("verification_status","DEMO" if rule.get("is_demo_or_provisional",True) else "VERIFIED")),p(rule["reason"]),
                                  p("Source: "+rule["source_document"]+" | Reference: "+str(rule["source_reference"] or "Not verified"))]))
    story.append(p("Review items and evidence","Heading2"))
    reviews=[rule for rule in snapshot["rule_evaluations"] if rule["status"]!="PASS"]
    for rule in reviews:
        story.append(p(rule["status"]+": "+rule["field_name"]+" - "+rule["reason"]))
    if not reviews:
        story.append(p("No configured check requested review; demo rules still require official-source verification."))
    for field in fields:
        bbox="; ".join(f"({point[0]:.3f}, {point[1]:.3f})" for point in field["bounding_box"])
        evidence=[p(field["field_name"].replace("_"," ")+" - "+field["image_side"],"Heading3"),
                  p("Source text: "+field["source_text"]),p(f"Confidence: {field['confidence']:.0%}; image: {field['image_id']}","SmallText"),
                  p("Machine extracted: "+field.get("machine_value",field["normalized_value"]).get("display",""),"SmallText"),
                  p("Human corrected: "+(field.get("corrected_value") or {}).get("display","Not corrected")+
                    (" | reviewed at "+str(field.get("corrected_at")) if field.get("corrected_at") else ""),"SmallText"),
                  p("Normalized bounding box: "+bbox,"SmallText")]
        block=Table([[evidence]],colWidths=[495],hAlign="LEFT")
        block.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),
                                   ("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),
                                   ("BOTTOMPADDING",(0,0),(-1,-1),0)]))
        story.append(block)
    def footer(canvas,doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
        canvas.line(16*mm,285*mm,194*mm,285*mm)
        canvas.setFont("Helvetica-Bold",8)
        canvas.setFillColor(colors.HexColor("#1d4ed8"))
        canvas.drawString(16*mm,288*mm,"PackSure AI - Inspection Assistance Report")
        canvas.setFont("Helvetica",8)
        canvas.setFillColor(colors.HexColor("#334155"))
        marker=" | DEMO / PROVISIONAL rules" if provisional else ""
        canvas.drawString(16*mm,12*mm,"Human verification required"+marker)
        canvas.drawRightString(195*mm,12*mm,"Page "+str(canvas.getPageNumber()))
        canvas.restoreState()
    doc=BaseDocTemplate(str(path),pagesize=A4,leftMargin=17*mm,rightMargin=17*mm,
                        topMargin=27*mm,bottomMargin=20*mm,title="PackSure AI Inspection Report",
                        author="PackSure AI")
    frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,id="report-body")
    doc.addPageTemplates(PageTemplate(id="report",frames=frame,onPageEnd=footer))
    doc.build(story)
