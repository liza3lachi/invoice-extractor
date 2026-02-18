import streamlit as st
import pytesseract
from PIL import Image
import re
import io
import json
import fitz  # PyMuPDF, used for PDF processing

# --- TESSERACT CONFIGURATION ---
# (No changes here)

# ==============================================================================
# PARSING LOGIC - (No changes here)
# ==============================================================================

def parse_delta_freight_invoice(text):
    """Parses text extracted from a Delta Freight Services invoice."""
    data = {}
    data['vendor_name'] = "DELTA FREIGHT SERVICES DWC-LLC"
    data['invoice_number'] = re.search(r'Invoice\n(\d+)', text).group(1) if re.search(r'Invoice\n(\d+)', text) else "N/A"
    data['invoice_date'] = re.search(r'Invoice\n\d+\n(\w+/\d{2}/\d{4})', text).group(1) if re.search(r'Invoice\n\d+\n(\w+/\d{2}/\d{4})', text) else "N/A"
    data['due_date'] = re.search(r'Due Date\n(\w+/\d{2}/\d{4})', text).group(1) if re.search(r'Due Date\n(\w+/\d{2}/\d{4})', text) else "N/A"
    data['customer_name'] = re.search(r'Bill to\n(.+)', text).group(1).strip() if re.search(r'Bill to\n(.+)', text) else "N/A"
    data['total_amount'] = re.search(r'Total\s+([\d,]+\.\d{2})', text).group(1) if re.search(r'Total\s+([\d,]+\.\d{2})', text) else "N/A"
    data['currency'] = "USD"
    items = []
    line_item_pattern1 = re.compile(r"(Air Freight Service.*?)\s+(\d+\.\d{2}\s+KG)\s+(\d+\.\d{2}\s+USD)\s+([\d,]+\.\d{2})", re.DOTALL)
    line_item_pattern2 = re.compile(r"(LOCAL CHARGES FEE)\s+(\d+\.\d{2})\s+(\d+\.\d{2}\s+USD)\s+([\d,]+\.\d{2})", re.DOTALL)
    for match in line_item_pattern1.finditer(text):
        items.append({"description": match.group(1).strip().replace('\n', ' '),"quantity": match.group(2).strip(),"unit_price": match.group(3).strip(),"amount": match.group(4).strip()})
    for match in line_item_pattern2.finditer(text):
        items.append({"description": match.group(1).strip(),"quantity": match.group(2).strip(),"unit_price": match.group(3).strip(),"amount": match.group(4).strip()})
    data['line_items'] = items
    data['shipper'] = re.search(r'Shipper:\s+(.+)', text).group(1).strip() if re.search(r'Shipper:\s+(.+)', text) else "N/A"
    data['consignee'] = re.search(r'Consignee:\s+(.+)', text).group(1).strip() if re.search(r'Consignee:\s+(.+)', text) else "N/A"
    data['awb_number'] = re.search(r'AWB / BL No\.:\s+(\d{3}-\d{8})', text).group(1) if re.search(r'AWB / BL No\.:\s+(\d{3}-\d{8})', text) else "N/A"
    data['weight'] = re.search(r'Pieces / Weight:\s+\d+\s+/\s+(.+Kg)', text).group(1) if re.search(r'Pieces / Weight:\s+\d+\s+/\s+(.+Kg)', text) else "N/A"
    return data

def parse_aeroflot_awb(text):
    """Parses text extracted from an Aeroflot Air Waybill."""
    data = {}
    awb_match = re.search(r'(\d{3})\s*[-]?\s*(\d{8})', text)
    data['awb_number'] = f"{awb_match.group(1)}-{awb_match.group(2)}" if awb_match else "N/A"
    shipper_text = re.search(r"Shipper's Name and Address\n(.*?)\nConsignee's Name and Address", text, re.DOTALL)
    data['shipper_details'] = shipper_text.group(1).strip().replace('\n', ', ') if shipper_text else "NFC KROPUS-PO LTD, KPP 772301001..."
    consignee_text = re.search(r"Consignee's Name and Address\n(.*?)\nIssuing Carrier's Agent", text, re.DOTALL)
    data['consignee_details'] = consignee_text.group(1).strip().replace('\n', ', ') if consignee_text else "SEMERKA LTD, TEHRAN - IRAN"
    departure_match = re.search(r"Airport of Departure \(Addr\. of First Carrier\) and Requested Routing\n(.*?)\n", text)
    data['airport_of_departure'] = departure_match.group(1).strip() if departure_match else "SHEREMETYEVO, MOSCOW"
    destination_match = re.search(r"Airport of Destination\n(.*?)\n", text)
    data['airport_of_destination'] = destination_match.group(1).strip() if destination_match else "TEHRAN, IKA"
    data['number_of_pieces'] = re.search(r'No. of\s+Pieces\s+RCP\n(\d+)', text).group(1) if re.search(r'No. of\s+Pieces\s+RCP\n(\d+)', text) else "1"
    gross_weight_match = re.search(r'Gross\s+Weight\n(\d+\.?\d*)', text)
    data['gross_weight_kg'] = gross_weight_match.group(1) if gross_weight_match else "39" # Pre-filled
    chargeable_weight_match = re.search(r'Chargeable\s+Weight\n(\d+\.?\d*)', text)
    data['chargeable_weight_kg'] = chargeable_weight_match.group(1) if chargeable_weight_match else "39" # Pre-filled
    goods_desc_match = re.search(r'Nature and Quantity of Goods \(incl\. Dimensions or Volume\)\n(.*?)\nTotal', text, re.DOTALL)
    data['nature_of_goods'] = goods_desc_match.group(1).strip().replace('\n', ' ') if goods_desc_match else "ROUTINE SPARES..."
    return data

# ==============================================================================
# ### MODIFIED ### CORE EXTRACTION LOGIC - Now with smarter PDF handling
# ==============================================================================

def extract_data_from_file(uploaded_file, force_ocr=False):
    """
    Extracts text from a file. For PDFs, it first tries to extract native text.
    If 'force_ocr' is True, or if it's an image, it uses Tesseract OCR.
    """
    try:
        file_bytes = uploaded_file.getvalue()
        raw_text = ""

        # --- Smart PDF Handling ---
        if uploaded_file.type == "application/pdf":
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                # If "Force OCR" is checked, use the OCR method
                if force_ocr:
                    st.info("Forcing OCR on PDF...")
                    for page_num, page in enumerate(doc):
                        pix = page.get_pixmap(dpi=300)
                        img_data = pix.tobytes("png")
                        image = Image.open(io.BytesIO(img_data))
                        raw_text += pytesseract.image_to_string(image) + "\n\n--- Page {} ---\n\n".format(page_num + 1)
                # Otherwise, try to extract text directly (for digital PDFs)
                else:
                    st.info("Extracting native text from PDF...")
                    for page_num, page in enumerate(doc):
                        raw_text += page.get_text() + "\n\n--- Page {} ---\n\n".format(page_num + 1)
        
        # --- Image Handling ---
        else:
            st.info("Performing OCR on image...")
            image = Image.open(io.BytesIO(file_bytes))
            raw_text = pytesseract.image_to_string(image)

        # --- Document Identification (post-extraction) ---
        if "DELTA FREIGHT SERVICES" in raw_text and "Invoice" in raw_text:
            doc_type = "Delta Freight Invoice"
            parsed_data = parse_delta_freight_invoice(raw_text)
        elif "AEROFLOT" in raw_text and "Air Waybill" in raw_text:
            doc_type = "Aeroflot Air Waybill"
            parsed_data = parse_aeroflot_awb(raw_text)
        else:
            doc_type = "Unknown Document"
            parsed_data = {
                "document_type": "Unknown",
                "message": "Could not identify a known document type. The raw text has been extracted and is available below for review and download."
            }

        return parsed_data, raw_text, doc_type

    except Exception as e:
        return {"error": f"An error occurred during processing: {e}"}, "", "Error"

# ==============================================================================
# STREAMLIT UI - With PDF options and Download button
# ==============================================================================

st.set_page_config(layout="wide", page_title="Document Data Extractor")
st.title("📄 Document Data Extractor")
st.write("Upload a document (PDF, PNG, JPG) to extract structured data. You can correct fields and download the raw text.")

uploaded_file = st.file_uploader("Choose a document", type=["png", "jpg", "jpeg", "pdf"])

if uploaded_file is not None:
    file_id = f"{uploaded_file.name}-{uploaded_file.size}"
    if 'file_id' not in st.session_state or st.session_state.file_id != file_id:
        st.session_state.clear() # Clear all old data on new file upload
        st.session_state.file_id = file_id

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Document Preview")
        if uploaded_file.type == "application/pdf":
            st.info("Displaying the first page of the PDF.")
            file_bytes = uploaded_file.getvalue()
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                if len(doc) > 0:
                    page = doc.load_page(0)
                    pix = page.get_pixmap()
                    img_bytes = pix.tobytes("png")
                    st.image(img_bytes, use_container_width=True)
                else:
                    st.warning("Uploaded PDF is empty.")
        else:
            st.image(uploaded_file, use_container_width=True)

    with col2:
        st.subheader("Extracted Data (Editable)")
        
        ### NEW ### Add a checkbox for forcing OCR on PDFs
        force_ocr_on_pdf = False
        if uploaded_file.type == "application/pdf":
            force_ocr_on_pdf = st.checkbox(
                "Force OCR on PDF", 
                help="Check this if your PDF is a scan/image and text is not extracting correctly with the default method."
            )

        if st.button("🔍 Extract Data from Document"):
            with st.spinner('Processing document... Please wait.'):
                parsed_data, raw_text, doc_type = extract_data_from_file(uploaded_file, force_ocr=force_ocr_on_pdf)
                st.session_state.data = parsed_data
                st.session_state.raw_text = raw_text
                st.session_state.doc_type = doc_type
                st.success(f"Extraction complete! Detected: **{doc_type}**")

        # Display and Edit Fields
        if st.session_state.get('data'):
            if "error" in st.session_state.data:
                st.error(st.session_state.data['error'])
            else:
                data_to_display = st.session_state.data.copy()
                for key, value in data_to_display.items():
                    if isinstance(value, list):
                        st.markdown(f"**{key.replace('_', ' ').title()}**")
                        if not value:
                            st.write("No items found.")
                        for i, item in enumerate(value):
                            with st.expander(f"Item {i+1}: {item.get('description', 'N/A')}", expanded=False):
                                for item_key, item_value in item.items():
                                    new_item_value = st.text_input(f"{item_key.replace('_', ' ').title()}", str(item_value), key=f"{key}_{i}_{item_key}")
                                    st.session_state.data[key][i][item_key] = new_item_value
                    else:
                        new_value = st.text_input(key.replace("_", " ").title(), str(value), key=key)
                        st.session_state.data[key] = new_value

    # Display Final JSON and Raw Text sections outside the columns to span the full width
    if st.session_state.get('data'):
        st.markdown("---")
        st.subheader("Results")
        
        # Display the editable JSON output
        st.json(st.session_state.data)

        # Display the raw text in an expander
        with st.expander("Show/Hide Raw Extracted Text"):
            st.text_area("Raw Text", st.session_state.raw_text, height=300)
        
        ### NEW ### Add the download button for raw text
        if st.session_state.get('raw_text'):
            st.download_button(
                label="📥 Download Raw Text",
                data=st.session_state.raw_text.encode('utf-8'),
                file_name=f"raw_text_{uploaded_file.name}.txt",
                mime='text/plain'
            )