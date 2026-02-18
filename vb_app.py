import streamlit as st
import pytesseract
from PIL import Image
import re
import io
import fitz
import cv2
import numpy as np

pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

def preprocess_image(image):
    img = np.array(image)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 2)
    return Image.fromarray(thresh)

def parse_generic_invoice(text):
    data = {}

    invoice_number = re.search(r'(invoice\s*(no|number)?[:\s]*)([A-Za-z0-9\-]+)', text, re.IGNORECASE)
    invoice_date = re.search(r'\b(\d{1,2}[\/\-\.\s]\d{1,2}[\/\-\.\s]\d{2,4})\b', text)
    total_amount = re.search(r'(total|amount due|grand total)[^\d]*([\d,]+\.\d{2})', text, re.IGNORECASE)
    currency = re.search(r'\b(USD|EUR|RUB|GBP|AED|IRR)\b', text)

    data["invoice_number"] = invoice_number.group(3) if invoice_number else "N/A"
    data["invoice_date"] = invoice_date.group(1) if invoice_date else "N/A"
    data["total_amount"] = total_amount.group(2) if total_amount else "N/A"
    data["currency"] = currency.group(1) if currency else "N/A"

    data["vendor_name"] = text.split("\n")[0].strip() if text else "N/A"

    return data

def parse_generic_awb(text):
    data = {}

    awb_match = re.search(r'\b\d{3}[- ]?\d{8}\b', text)
    data["awb_number"] = awb_match.group(0) if awb_match else "N/A"

    shipper_match = re.search(r'Shipper.*?\n(.*)', text, re.IGNORECASE)
    consignee_match = re.search(r'Consignee.*?\n(.*)', text, re.IGNORECASE)

    data["shipper"] = shipper_match.group(1).strip() if shipper_match else "N/A"
    data["consignee"] = consignee_match.group(1).strip() if consignee_match else "N/A"

    airport_codes = re.findall(r'\b[A-Z]{3}\b', text)
    data["airports_detected"] = airport_codes[:5] if airport_codes else []

    weight_match = re.search(r'(\d+\.?\d*)\s*(kg|kgs)', text, re.IGNORECASE)
    data["weight_kg"] = weight_match.group(1) if weight_match else "N/A"

    pieces_match = re.search(r'(\d+)\s*(pieces|pcs)', text, re.IGNORECASE)
    data["number_of_pieces"] = pieces_match.group(1) if pieces_match else "N/A"

    return data

def extract_data_from_file(uploaded_file, force_ocr=False):
    try:
        file_bytes = uploaded_file.getvalue()
        raw_text = ""

        if uploaded_file.type == "application/pdf":
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                if force_ocr:
                    for page in doc:
                        pix = page.get_pixmap(dpi=300)
                        img_data = pix.tobytes("png")
                        image = Image.open(io.BytesIO(img_data))
                        processed = preprocess_image(image)
                        raw_text += pytesseract.image_to_string(processed, config="--oem 3 --psm 6") + "\n\n"
                else:
                    for page in doc:
                        raw_text += page.get_text() + "\n\n"
        else:
            image = Image.open(io.BytesIO(file_bytes))
            processed = preprocess_image(image)
            raw_text = pytesseract.image_to_string(processed, config="--oem 3 --psm 6")

        text_lower = raw_text.lower()

        invoice_pattern = re.search(r'invoice', text_lower)
        awb_pattern = re.search(r'\b\d{3}[- ]?\d{8}\b', raw_text)

        if invoice_pattern and re.search(r'\d{1,2}[\/\-\.\s]\d{1,2}[\/\-\.\s]\d{2,4}', raw_text):
            doc_type = "Invoice"
            parsed_data = parse_generic_invoice(raw_text)

        elif awb_pattern or "waybill" in text_lower or "awb" in text_lower:
            doc_type = "Air Waybill"
            parsed_data = parse_generic_awb(raw_text)

        else:
            doc_type = "Unknown Document"
            parsed_data = {
                "document_type": "Unknown",
                "message": "Could not confidently classify this document."
            }

        return parsed_data, raw_text, doc_type

    except Exception as e:
        return {"error": f"Processing error: {e}"}, "", "Error"

st.set_page_config(layout="wide", page_title="Document Data Extractor")
st.title("📄 Document Data Extractor")

uploaded_file = st.file_uploader("Choose a document", type=["png", "jpg", "jpeg", "pdf"])

if uploaded_file is not None:
    col1, col2 = st.columns(2)

    with col1:
        if uploaded_file.type == "application/pdf":
            file_bytes = uploaded_file.getvalue()
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                if len(doc) > 0:
                    page = doc.load_page(0)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    st.image(img_bytes, use_container_width=True)
        else:
            st.image(uploaded_file, use_container_width=True)

    with col2:
        force_ocr = False
        if uploaded_file.type == "application/pdf":
            force_ocr = st.checkbox("Force OCR on PDF")

        if st.button("🔍 Extract Data"):
            with st.spinner("Processing..."):
                parsed_data, raw_text, doc_type = extract_data_from_file(uploaded_file, force_ocr)
                st.session_state.data = parsed_data
                st.session_state.raw_text = raw_text
                st.session_state.doc_type = doc_type
                st.success(f"Detected: {doc_type}")

        if st.session_state.get("data"):
            st.json(st.session_state.data)

    if st.session_state.get("raw_text"):
        with st.expander("Raw Text"):
            st.text_area("Extracted Text", st.session_state.raw_text, height=300)

        st.download_button(
            label="Download Raw Text",
            data=st.session_state.raw_text.encode("utf-8"),
            file_name=f"raw_text_{uploaded_file.name}.txt",
            mime="text/plain"
        )
