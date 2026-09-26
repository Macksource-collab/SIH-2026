import { useEffect, useRef, useState } from "react";

import { apiFetch } from "./api.js";

import AnalysisPanel from "./AnalysisPanel.jsx";

const SIDES = ["front", "back", "left", "right", "top", "bottom"];
const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const sideLabel = (side) => side[0].toUpperCase() + side.slice(1);

export default function InspectionForm({ inspectionId, onStartAnother }) {
  const [images, setImages] = useState([]);
  const [side, setSide] = useState("front");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const previewUrls = useRef(new Set());

  useEffect(() => {
    const urls = previewUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const availableSides = SIDES.filter((value) => !images.some((image) => image.side === value));
  const selectedSide = availableSides.includes(side) ? side : availableSides[0] || "";
  const pending = images.filter((image) => image.status !== "Uploaded");
  const complete = images.length > 0 && pending.length === 0;

  function chooseFile(event) {
    const file = event.target.files[0];
    event.target.value = "";
    setError("");
    if (!file) return;
    if (!selectedSide || images.some((image) => image.side === selectedSide)) {
      setError("Each package side can have only one image.");
    } else if (!ALLOWED_TYPES.includes(file.type)) {
      setError("Choose a PNG, JPG, JPEG, or WEBP image.");
    } else if (file.size === 0) {
      setError("This file is empty. Choose another image.");
    } else if (file.size > MAX_FILE_SIZE) {
      setError("Each image must be 10 MB or smaller.");
    } else {
      const preview = URL.createObjectURL(file);
      previewUrls.current.add(preview);
      setImages((current) => [...current, { side: selectedSide, file, preview, status: "Selected", error: "" }]);
    }
  }

  function removeImage(image) {
    URL.revokeObjectURL(image.preview);
    previewUrls.current.delete(image.preview);
    setImages((current) => current.filter((item) => item.side !== image.side));
    setError("");
  }

  function updateImage(side, changes) {
    setImages((current) => current.map((image) => image.side === side ? { ...image, ...changes } : image));
  }

  async function uploadImages(event) {
    event.preventDefault();
    if (loading || !pending.length) return;
    setLoading(true);
    setError("");
    // Upload sequentially so each card has a clear status and failures can be retried.
    for (const image of pending) {
      updateImage(image.side, { status: "Uploading", error: "" });
      try {
        const body = new FormData();
        body.append("file", image.file);
        body.append("image_side", image.side);
        const response = await apiFetch(`/inspections/${inspectionId}/images`, {
          method: "POST", body, signal: AbortSignal.timeout(60000),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "Upload failed. Please try again.");
        }
        updateImage(image.side, { status: "Uploaded", fileId: data.file_id });
      } catch (error) {
        updateImage(image.side, { status: "Failed", error: error.name === "TimeoutError"
          ? "Upload timed out. The server may have saved it; a retry will never overwrite that side."
          : error instanceof TypeError ? "Cannot reach the backend. Check the connection and retry." : error.message });
      }
    }
    setLoading(false);
  }

  return (
    <section className="panel inspection-panel" aria-labelledby="inspection-title">
      <h2 id="inspection-title">New Inspection</h2>
      <p className="inspection-id">Inspection ID: {inspectionId}</p>
      <p>Add one image per package side. PNG, JPG/JPEG, or WEBP, up to 10 MB each. You do not need all six sides.</p>
      <p className="capture-hint">Keep label text sharp, fill the frame, and avoid glare. On supported phones and tablets, the camera opens facing the package.</p>
      <form onSubmit={uploadImages} aria-busy={loading}>
        <label htmlFor="image-side">Package side</label>
        <select id="image-side" value={selectedSide} onChange={(event) => setSide(event.target.value)} disabled={loading || !availableSides.length}>
          {!availableSides.length && <option value="">All six sides added</option>}
          {SIDES.map((value) => <option key={value} value={value} disabled={!availableSides.includes(value)}>{sideLabel(value)}</option>)}
        </select>
        <label htmlFor="product-image">Product image</label>
        <input id="product-image" type="file" accept="image/*" capture="environment"
          onChange={chooseFile} disabled={loading || !selectedSide} aria-describedby="upload-feedback" />
        <div className="inspection-images">
          {images.map((image) => <article className="image-card" key={image.side} aria-label={`${sideLabel(image.side)} image`}>
            <h3>{sideLabel(image.side)}</h3>
            <img className="product-preview" src={image.preview} alt={`${sideLabel(image.side)} package preview`} />
            <p className="selected-filename">{image.file.name}</p>
            <p role="status" className={image.status === "Uploaded" ? "online" : image.status === "Failed" ? "offline" : ""}>{image.status}</p>
            {image.error && <p className="upload-error" role="alert">{image.error}</p>}
            {image.status !== "Uploaded" && <button className="secondary-button" type="button" disabled={loading} onClick={() => removeImage(image)} aria-label={`Remove ${sideLabel(image.side)} image`}>Remove</button>}
          </article>)}
        </div>
        <button className="primary-button" type="submit" disabled={!pending.length || loading}>
          {loading ? "Uploading Inspection Images…" : "Upload Inspection Images"}
        </button>
        <div id="upload-feedback" aria-live="polite">
          {error && <p className="upload-error" role="alert">{error}</p>}
          {complete && <p className="upload-success" role="status">All {images.length} selected images uploaded successfully for this inspection.</p>}
          {images.some((image) => image.status === "Failed") && <p>Some images failed. Successful uploads are kept; the upload button retries only the remaining images.</p>}
        </div>
        {complete && <button className="secondary-button" type="button" disabled={loading} onClick={onStartAnother}>Start Another Inspection</button>}
      </form>
      {complete && <AnalysisPanel inspectionId={inspectionId} />}
    </section>
  );
}
