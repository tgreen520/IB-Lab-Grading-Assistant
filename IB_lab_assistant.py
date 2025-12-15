import streamlit as st
import anthropic
import base64
import pandas as pd
import os
import zipfile
import time
import re
from docx import Document
from io import BytesIO

# --- 1. PAGE SETUP (MUST BE FIRST) ---
st.set_page_config(
    page_title="IB Lab Assistant", 
    page_icon="🧪", 
    layout="wide"
)

# --- 2. CONFIGURATION & SECRETS ---
if "ANTHROPIC_API_KEY" in st.secrets:
    API_KEY = st.secrets["ANTHROPIC_API_KEY"]
elif "ANTHROPIC_API_KEY" in os.environ:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
else:
    st.error("🚨 API Key not found!")
    st.info("On Streamlit Cloud, add your key to the 'Secrets' settings.")
    st.stop()

# --- 3. HARDCODED RUBRIC (UPDATED FOR IB CHEMISTRY STANDARDS) ---
IB_RUBRIC = """TOTAL: 100 POINTS (10 pts per section)

1. FORMATTING (10 pts):
- Criteria: Third-person passive voice, professional tone, superscripts/subscripts used correctly.
- DEDUCTIONS: 1-2 subscript errors = -0.5 pts. 3+ errors = -1.0 pt.

2. INTRODUCTION (10 pts):
- Criteria: Clear objective, background theory, balanced equations.
- OBJECTIVE: Must be explicit. If missing, -1.0 pt.

3. HYPOTHESIS (10 pts):
- Criteria: Specific prediction with scientific justification.

4. VARIABLES (10 pts):
- Criteria: IV, DV, 3+ Controls.
- SCORING: 
  * 10/10: All defined + explanations.
  * 9.5/10: DV measurement vague (-0.5).
  * 9.0/10: Explanations missing (-1.0).

5. PROCEDURES & MATERIALS (10 pts):
- Criteria: Numbered steps, quantities, safety, diagram.
- UNCERTAINTIES & PRECISION:
  * Uncertainties can be listed here OR in Data Tables.
  * If Uncertainties are completely missing:
    - If only 1 measuring device used: -0.5 pts.
    - If >1 measuring devices used: -1.0 pt.
  * Uncertainties not reported with correct precision: -0.5 pts.
  * Instrument precision does not match uncertainty precision: -0.5 pts.
  * Diagram missing: -0.5 pt.

6. RAW DATA (10 pts):
- Criteria: Qualitative observations, tables, units, sig figs.
- REQUIREMENT: Uncertainties must be reported in Data Tables (headers or cells).

7. DATA ANALYSIS (10 pts):
- UNCERTAINTY PROPAGATION (IB CHEMISTRY STANDARD):
  * MUST use Absolute Uncertainty (for + / -) and Percentage Uncertainty (for * / /).
  * NOTE: Intermediate steps are NOT required. Do NOT deduct for missing intermediate steps if the result is correct.
  * No propagation attempted: -2.0 pts.
  * Propagation incorrect (wrong formula/logic): -1.0 pt.
- GRAPHS (Bar or Scatter allowed based on context):
  * Graph Missing: -2.0 pts. (NOTE: If Graph is missing, do NOT deduct for missing axis labels or missing averages. Max deduction is -2.0).
  * Graph Present but Axis labels/Units missing: -1.0 pt.
  * MULTIPLE TRIALS RULE: If >1 trial performed, graph MUST show AVERAGES. (If missing: -2.0 pts).
  * SCATTER PLOT REQ: Trendline, Equation, R^2 (if applicable). 
  * BAR GRAPH REQ: Average values shown.

8. CONCLUSION (10 pts) [STRICT DEDUCTIONS]:
- UNCERTAINTY IMPACT (CROSS-CHECK EVALUATION): 
  * Check BOTH Conclusion and Evaluation.
  * If discussed in EITHER section: 0 deduction.
  * Mentioned but NOT discussed fully (in either): -1.0 pt (Partial).
  * Completely missing in BOTH Conclusion AND Evaluation: -2.0 pts.
  * NOTE: When crediting this, explicitly state: "Uncertainty discussion can be in the conclusion or evaluation section."
- LITERATURE COMPARISON:
  * Must compare results to published literature/accepted values to support or refute findings.
  * If missing: -1.0 pt.
- IV/DV RELATIONSHIP: Must explain graph trend. (If poor: -1.0)
- THEORY: Connect to chemical theory.
  * Explained fully: 0 deduction.
  * Discussed but incomplete explanation: -1.0 pt.
  * Completely missing: -2.0 pts.
- QUANTITATIVE SUPPORT: Must cite specific numbers. (If missing: -2.0)
- QUALITATIVE SUPPORT: Must cite observations. (If missing: -0.5)
- STATISTICS: Explain R/R^2 (if Scatter used).

9. EVALUATION (10 pts) [STRICT QUALITY GATES]:
- REQUIREMENT: List errors + Specific Directional Impact + Specific Improvement.
- IMPACT SCORING:
  * Impact defined for 100% of errors = 2 pts.
  * Impact defined for SOME (not all) errors = 1 pt (Deduct 1.0).
  * No impact defined = 0 pts (Deduct 2.0).
- IMPROVEMENT SCORING:
  * Specific equipment named = 2 pts.
  * Vague ("use better scale") = 1.5 pts (Deduct 0.5).
  * Generic ("be careful") = 0 pts (Deduct 2.0).

10. REFERENCES (10 pts):
- Criteria: 3+ credible sources = 9.0 min score.
- FORMATTING: Minor errors (italics, periods, capitalization) = 0 deduction. Only deduct if citation is unintelligible or missing.
"""

# --- 4. SYSTEM PROMPT (UPDATED LOGIC) ---
SYSTEM_PROMPT = """You are an expert IB Chemistry Lab Grader. 
Your goal is to grade student lab reports according to the specific IB Chemistry standards below.

### 🧠 SCORING ALGORITHMS (STRICT ENFORCEMENT):

1.  **HIDDEN MATH (CRITICAL):**
    * You MUST perform your score calculations inside a special block: `<<<MATH: 10.0 - 0.5 = 9.5>>>`.
    * This block must appear **immediately before** the section header.
    * You MUST list every specific deduction in this block to ensure the subtraction is correct.
    * *Example:* `<<<MATH: Starting 10.0. Deductions: Diagram (-0.5). Calculation: 10.0 - 0.5 = 9.5.>>>`
    * The system will remove these blocks before showing the user, so be precise inside them.

2.  **DATA ANALYSIS (Section 7) - NO DOUBLE JEOPARDY:**
    * **Scenario A (No Graph):** Deduct 2.0 points. **STOP.** * Do **NOT** deduct for "Missing Averages" (-2.0) if there is no graph.
      * Do **NOT** deduct for "Missing Axis Labels" (-1.0) if there is no graph.
      * **Max Deduction for a missing graph is 2.0.**
    * **Scenario B (Graph Exists):** * Check axis labels (missing? -1.0). 
      * Check if it graphs Averages (if multiple trials). If raw data graphed -> -2.0.

3.  **CONCLUSION (Section 8) - CROSS-CHECK LOGIC:**
    * **Uncertainty Impact:** Check BOTH Conclusion and Evaluation. If discussed in EITHER -> **0 Deduction**. Only deduct if missing from BOTH.
    * **Literature Comparison:** Check if they compared data to published literature. If NO -> **Deduct 1.0 point**.
    * **Theory:** Full explanation = 0. Incomplete = -1.0. Missing = -2.0.
    * **Quantitative Data:** Missing = -2.0.

4.  **REFERENCES (Section 10) - STRICT LENIENCY:**
    * **Formatting Errors:** If you see minor formatting errors (dates, italics, punctuation), mention them in "Improvements" but deduct **0.0 points**.
    * **Score:** If there are 3+ sources, the score MUST be **10.0/10** unless a source is actually missing.

### OUTPUT FORMAT:
Please strictly use the following format.

# 📝 SCORE: [Total Points]/100
STUDENT: [Filename]

**📊 OVERALL SUMMARY & VISUAL ANALYSIS:**
* [1-2 sentences on quality]
* [Critique of graphs/images]

**📝 DETAILED RUBRIC BREAKDOWN:**

<<<MATH: ...>>>
**1. FORMATTING: [Score]/10**
* **✅ Strengths:** [Tone/Voice]
* **⚠️ Improvements:** [List specific errors only. If none, write "None".]

<<<MATH: ...>>>
**2. INTRODUCTION: [Score]/10**
* **✅ Strengths:** [Objective/Theory]
* **⚠️ Improvements:** [Explanation]

<<<MATH: ...>>>
**3. HYPOTHESIS: [Score]/10**
* **✅ Strengths:** [Prediction]
* **⚠️ Improvements:** [Justification]

<<<MATH: ...>>>
**4. VARIABLES: [Score]/10**
* **✅ Strengths:** [IV/DV/Controls]
* **⚠️ Improvements:** [Vagueness]

<<<MATH: ...>>>
**5. PROCEDURES & MATERIALS: [Score]/10**
* **✅ Strengths:** [Safety/Steps]
* **⚠️ Improvements:** [**UNCERTAINTY CHECK:** "Uncertainties found in Materials/Tables? (-0.5 if 1 missing, -1.0 if >1 missing). Precision match? (-0.5)."]

<<<MATH: ...>>>
**6. RAW DATA: [Score]/10**
* **✅ Strengths:** [Tables/Units]
* **⚠️ Improvements:** [Sig Fig check]

<<<MATH: ...>>>
**7. DATA ANALYSIS: [Score]/10**
* **✅ Strengths:** [Calculations/Graph]
* **⚠️ Improvements:** [**IB PROPAGATION & GRAPH CHECK:** - "Uncertainty Propagation: Missing (-2) or Incorrect (-1)?"
  - "Graph: Missing (-2)? (If missing, do not deduct for axes/averages)."
  - "Axes/Averages: (Only check if graph exists)."]

<<<MATH: ...>>>
**8. CONCLUSION: [Score]/10**
* **✅ Strengths:** [Data citation]
* **⚠️ Improvements:** [**SCORING LOGIC:** - "Literature Comparison: Did you compare to published literature? (Missing = -1)."
  - "Uncertainty Impact: (Note: Uncertainty discussion can be in the conclusion or evaluation section). Missing in BOTH = -2, Partial = -1."
  - "Theory: Missing (-2) or Incomplete (-1)?"
  - "Quant Data: Missing (-2)?"]

<<<MATH: ...>>>
**9. EVALUATION: [Score]/10**
* **✅ Strengths:** [Error list]
* **⚠️ Improvements:** [Impact/Improvement specificity]

<<<MATH: ...>>>
**10. REFERENCES: [Score]/10**
* **✅ Strengths:** [Source count]
* **⚠️ Improvements:** [Formatting (No deduction for minor errors)]

**💡 TOP 3 ACTIONABLE STEPS FOR NEXT TIME:**
1. [Step 1]
2. [Step 2]
3. [Step 3]
"""

# Initialize Session State
if 'saved_sessions' not in st.session_state:
    st.session_state.saved_sessions = {}
if 'current_results' not in st.session_state:
    st.session_state.current_results = []
if 'current_session_name' not in st.session_state:
    st.session_state.current_session_name = "New Grading Session"

client = anthropic.Anthropic(api_key=API_KEY)

# --- 5. HELPER FUNCTIONS ---
def encode_file(uploaded_file):
    try:
        uploaded_file.seek(0)
        return base64.b64encode(uploaded_file.read()).decode('utf-8')
    except Exception as e:
        st.error(f"Error encoding file: {e}")
        return None

def get_media_type(filename):
    ext = filename.lower().split('.')[-1]
    media_types = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'gif': 'image/gif', 'webp': 'image/webp', 'pdf': 'application/pdf'
    }
    return media_types.get(ext, 'image/jpeg')

def get_para_text_with_formatting(para):
    """Iterate through runs to capture subscript/superscript formatting."""
    text_parts = []
    for run in para.runs:
        text = run.text
        if run.font.subscript:
            text = f"<sub>{text}</sub>"
        elif run.font.superscript:
            text = f"<sup>{text}</sup>"
        text_parts.append(text)
    return "".join(text_parts)

def extract_text_from_docx(file):
    try:
        file.seek(0) 
        doc = Document(file)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(get_para_text_with_formatting(para))
        if doc.tables:
            full_text.append("\n--- DETECTED TABLES ---\n")
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        cell_content = []
                        for para in cell.paragraphs:
                            cell_content.append(get_para_text_with_formatting(para))
                        row_text.append(" ".join(cell_content).strip())
                    full_text.append(" | ".join(row_text))
                full_text.append("\n") 
        return "\n".join(full_text)
    except Exception as e:
        return f"Error reading .docx file: {e}"

def extract_images_from_docx(file):
    images = []
    try:
        file.seek(0)
        with zipfile.ZipFile(file) as z:
            for filename in z.namelist():
                if filename.startswith('word/media/') and filename.split('.')[-1].lower() in ['png', 'jpg', 'jpeg', 'gif']:
                    img_data = z.read(filename)
                    b64_img = base64.b64encode(img_data).decode('utf-8')
                    ext = filename.split('.')[-1].lower()
                    images.append({
                        "type": "image",
                        "source": {
                            "type": "base64", 
                            "media_type": f"image/{'jpeg' if ext=='jpg' else ext}", 
                            "data": b64_img
                        }
                    })
    except Exception as e:
        print(f"Image extraction failed: {e}")
    return images

def process_uploaded_files(uploaded_files):
    final_files = []
    IGNORED_FILES = {'.ds_store', 'desktop.ini', 'thumbs.db', '__macosx'}
    VALID_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'docx'}
    file_counts = {"pdf": 0, "docx": 0, "image": 0, "ignored": 0}

    for file in uploaded_files:
        file_name_lower = file.name.lower()
        if file_name_lower in IGNORED_FILES or file_name_lower.startswith('._'):
            continue
        if file_name_lower.endswith('.zip'):
            try:
                with zipfile.ZipFile(file) as z:
                    for filename in z.namelist():
                        clean_name = filename.lower()
                        if any(x in clean_name for x in IGNORED_FILES) or filename.startswith('.'): continue
                        ext = clean_name.split('.')[-1]
                        if ext in VALID_EXTENSIONS:
                            file_bytes = z.read(filename)
                            virtual_file = BytesIO(file_bytes)
                            virtual_file.name = os.path.basename(filename)
                            final_files.append(virtual_file)
                            if ext == 'docx': file_counts['docx'] += 1
                            elif ext == 'pdf': file_counts['pdf'] += 1
                            else: file_counts['image'] += 1
            except Exception as e:
                st.error(f"Error unzipping {file.name}: {e}")
        else:
            ext = file_name_lower.split('.')[-1]
            if ext in VALID_EXTENSIONS:
                final_files.append(file)
                if ext == 'docx': file_counts['docx'] += 1
                elif ext == 'pdf': file_counts['pdf'] += 1
                else: file_counts['image'] += 1
            else:
                file_counts['ignored'] += 1
    return final_files, file_counts

def clean_hidden_math(text):
    """Removes the <<<MATH: ... >>> blocks from the AI output."""
    clean_text = re.sub(r'<<<MATH:.*?>>>', '', text, flags=re.DOTALL)
    return clean_text.strip()

def recalculate_total_score(text):
    try:
        pattern = r"\d+\.\s+[A-Za-z\s&]+:\s+([\d\.]+)/10"
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            total_score = sum(float(m) for m in matches)
            if total_score.is_integer():
                total_score = int(total_score)
            else:
                total_score = round(total_score, 1)
            text = re.sub(r"#\s*📝\s*SCORE:\s*[\d\.]+/100", f"# 📝 SCORE: {total_score}/100", text, count=1)
    except Exception as e:
        print(f"Error recalculating score: {e}")
    return text

def parse_feedback_for_csv(text):
    data = {}
    clean_text = re.sub(r'[*#]', '', text) 
    try:
        summary_match = re.search(r"OVERALL SUMMARY.*?:\s*\n(.*?)(?=1\.|DETAILED)", clean_text, re.DOTALL | re.IGNORECASE)
        if summary_match:
            raw_summary = summary_match.group(1).strip()
            data["Overall Summary"] = re.sub(r'[\r\n]+', ' ', raw_summary)
        else:
            data["Overall Summary"] = "Summary not found"
    except Exception as e:
        data["Overall Summary"] = f"Parsing Error: {e}"

    sections = re.findall(r"(\d+)\.\s+([A-Za-z\s&]+):\s+([\d\.]+)/10\s*\n(.*?)(?=\n\d+\.|\Z|💡)", clean_text, re.DOTALL)
    for _, name, score, content in sections:
        col_name = name.strip().title()
        data[f"{col_name} Score"] = score
        cleaned_feedback = re.sub(r'[\r\n]+', ' ', content.strip())
        data[f"{col_name} Feedback"] = cleaned_feedback
    return data

def grade_submission(file, model_id):
    ext = file.name.split('.')[-1].lower()
    
    # Updated Prompt Construction to include new requirements in user message
    user_instructions = (
        "Please grade this lab report based on the provided rubric.\n"
        "⚠️ CRITICAL NEW INSTRUCTIONS:\n"
        "1. **MATERIALS (Section 5):** Look for uncertainty values (±) in the Materials list OR in Data Table headers. If found, count as valid.\n"
        "   - If completely MISSING: Deduct 0.5 (if 1 device used) or 1.0 (if >1 devices used).\n"
        "2. **DATA ANALYSIS (Section 7):**\n"
        "   - **Uncertainty Propagation:** You MUST use **IB CHEMISTRY STANDARDS**.\n"
        "   - **Formulas:** Look for Absolute Uncertainty (summing errors) and Percentage Uncertainty (summing percentages). Do NOT look for Physics quadrature.\n"
        "   - **Note:** Do NOT deduct points if the student did not show the intermediate step of converting absolute uncertainties to percentages. As long as the calculation/logic is correct, it is fine.\n"
        "   - **Averages:** If multiple trials were done, the graph MUST be of the AVERAGES. If they graphed raw trials -> Deduct 2 pts.\n"
        "3. **CONCLUSION:**\n"
        "   - **Uncertainty Impact:** CHECK BOTH SECTIONS (Conclusion & Evaluation). If discussed in either -> NO DEDUCTION. Only deduct if missing from BOTH.\n"
        "   - **Literature Comparison:** Check if they compared data to published literature. If NO -> Deduct 1.0 pt.\n"
        "   - **Theory:** If mentioned but explanation is incomplete -> Deduct 1.0 pt. If completely missing -> Deduct 2.0 pts.\n"
    )

    if ext == 'docx':
        text_content = extract_text_from_docx(file)
        if len(text_content.strip()) < 50:
            text_content += "\n\n[SYSTEM NOTE: Very little text extracted.]"
            
        prompt_text = (
            f"{user_instructions}\n"
            "--- RUBRIC START ---\n" + IB_RUBRIC + "\n--- RUBRIC END ---\n\n"
            "STUDENT TEXT:\n" + text_content
        )
        
        user_message = [{"type": "text", "text": prompt_text}]
        images = extract_images_from_docx(file)
        if images:
            user_message.extend(images)
    else:
        base64_data = encode_file(file)
        if not base64_data: return "Error processing file."
        media_type = get_media_type(file.name)
        
        prompt_text = (
            f"{user_instructions}\n"
            "--- RUBRIC START ---\n" + IB_RUBRIC + "\n--- RUBRIC END ---\n"
        )
        
        user_message = [
            {"type": "text", "text": prompt_text},
            {"type": "document" if media_type == 'application/pdf' else "image",
             "source": {"type": "base64", "media_type": media_type, "data": base64_data}}
        ]

    max_retries = 5 
    retry_delay = 5 
    
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model_id,
                max_tokens=3500,
                temperature=0.0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}]
            )
            raw_text = response.content[0].text
            
            # 1. Clean the Hidden Math (so user doesn't see it)
            clean_text = clean_hidden_math(raw_text)
            
            # 2. Recalculate Total (Just in case)
            final_text = recalculate_total_score(clean_text)
            
            return final_text
            
        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            if isinstance(e, anthropic.APIStatusError) and e.status_code == 529:
                time.sleep(retry_delay * (attempt + 1))
                continue
            if isinstance(e, anthropic.RateLimitError):
                time.sleep(retry_delay * (attempt + 1))
                continue
            return f"⚠️ Error: {str(e)}"
        except Exception as e:
            return f"⚠️ Error: {str(e)}"

def parse_score(text):
    try:
        match = re.search(r"#\s*📝\s*SCORE:\s*([\d\.]+)/100", text)
        if match: return match.group(1).strip()
        match = re.search(r"SCORE:\s*([\d\.]+)/100", text)
        if match: return match.group(1).strip()
    except Exception as e:
        print(f"Error parsing score: {e}")
    return "N/A"

def write_markdown_to_docx(doc, text):
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if line.startswith('# ') or line.startswith('STUDENT:'): 
            clean = line.replace('# ', '').replace('*', '').strip()
            doc.add_heading(clean, level=2) 
            continue
        if line.startswith('### '):
            clean = line.replace('### ', '').replace('*', '').strip()
            doc.add_heading(clean, level=3)
            continue
        if line.startswith('## '): 
            clean = line.replace('## ', '').replace('*', '').strip()
            doc.add_heading(clean, level=2)
            continue
        if line.startswith('---') or line.startswith('___'):
            continue
        if line.startswith('* ') or line.startswith('- '):
            p = doc.add_paragraph(style='List Bullet')
            content = line[2:] 
        else:
            p = doc.add_paragraph()
            content = line
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                clean_text = part[2:-2].replace('*', '') 
                run = p.add_run(clean_text)
                run.bold = True
            else:
                p.add_run(part.replace('*', '')) 

def create_master_doc(results, session_name):
    doc = Document()
    for item in results:
        write_markdown_to_docx(doc, item['Feedback'])
        doc.add_page_break()
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()

def create_zip_bundle(results):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for item in results:
            doc = Document()
            write_markdown_to_docx(doc, item['Feedback'])
            doc_buffer = BytesIO()
            doc.save(doc_buffer)
            safe_name = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
            z.writestr(safe_name, doc_buffer.getvalue())
    return zip_buffer.getvalue()

def display_results_ui():
    if not st.session_state.current_results:
        return
    st.divider()
    st.subheader(f"📊 Results: {st.session_state.current_session_name}")
    results_list = []
    for item in st.session_state.current_results:
        row_data = {"Filename": item['Filename'], "Overall Score": item['Score']}
        feedback_data = parse_feedback_for_csv(item['Feedback'])
        row_data.update(feedback_data)
        results_list.append(row_data)
    csv_df = pd.DataFrame(results_list)
    cols = list(csv_df.columns)
    priority = ['Filename', 'Overall Score', 'Overall Summary']
    remaining = [c for c in cols if c not in priority]
    remaining.sort(key=lambda x: (x.split(' ')[0], 'Feedback' in x)) 
    final_cols = [c for c in priority if c in cols] + remaining
    csv_df = csv_df[final_cols]
    csv_data = csv_df.to_csv(index=False).encode('utf-8-sig') 
    master_doc_data = create_master_doc(st.session_state.current_results, st.session_state.current_session_name)
    zip_data = create_zip_bundle(st.session_state.current_results)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📄 Google Docs Compatible (.docx)", master_doc_data, f'{st.session_state.current_session_name}_Docs.docx', "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
    with col2:
        st.download_button("📦 Student Bundle (.zip)", zip_data, f'{st.session_state.current_session_name}_Students.zip', "application/zip", use_container_width=True)
    with col3:
        st.download_button("📊 Detailed CSV Export", csv_data, f'{st.session_state.current_session_name}_Detailed.csv', "text/csv", use_container_width=True)
    tab1, tab2 = st.tabs(["📊 Gradebook View", "📝 Detailed Feedback"])
    with tab1:
        st.dataframe(csv_df, use_container_width=True)
    with tab2:
        for item in st.session_state.current_results:
            with st.expander(f"📄 {item['Filename']} (Score: {item['Score']})"):
                st.markdown(item['Feedback'])

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuration")
    user_model_id = st.text_input("🤖 Model ID", value="claude-sonnet-4-5-20250929")
    st.divider()
    st.header("💾 History Manager")
    save_name = st.text_input("Session Name", placeholder="e.g. Period 3 - Kinetics")
    if st.button("💾 Save Session"):
        if st.session_state.current_results:
            st.session_state.saved_sessions[save_name] = st.session_state.current_results
            st.success(f"Saved '{save_name}'!")
        else:
            st.warning("No results to save yet.")
    if st.session_state.saved_sessions:
        st.divider()
        st.subheader("📂 Load Session")
        selected_session = st.selectbox("Select Batch", list(st.session_state.saved_sessions.keys()))
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Load"):
                st.session_state.current_results = st.session_state.saved_sessions[selected_session]
                st.session_state.current_session_name = selected_session
                st.rerun()
        with col2:
            if st.button("🗑️ Delete"):
                del st.session_state.saved_sessions[selected_session]
                st.rerun()
    st.divider() 
    with st.expander("View Grading Criteria"):
        st.text(IB_RUBRIC)

# --- 7. MAIN INTERFACE ---
st.title("🧪 IB Lab Assistant")
st.caption(f"Current Session: **{st.session_state.current_session_name}**")
st.info("💡 **Tip:** To upload a folder, open it, press `Ctrl+A` (Select All), and drag everything here.")

raw_files = st.file_uploader(
    "📂 Upload Reports (PDF, Word, Images, ZIP)", 
    type=['pdf', 'docx', 'png', 'jpg', 'jpeg', 'zip'], 
    accept_multiple_files=True
)

processed_files = []
if raw_files:
    processed_files, counts = process_uploaded_files(raw_files)
    if len(processed_files) > 0:
        st.success(f"✅ Found **{len(processed_files)}** valid reports.")
        st.caption(f"📄 PDFs: {counts['pdf']} | 📝 Word Docs: {counts['docx']} | 🖼️ Images: {counts['image']}")
        if counts['ignored'] > 0:
            st.warning(f"⚠️ {counts['ignored']} files were ignored.")
    else:
        if raw_files:
            st.warning("No valid PDF, Word, or Image files found.")

if st.button("🚀 Grade Reports", type="primary", disabled=not processed_files):
    st.write("---")
    progress = st.progress(0)
    status = st.empty()
    new_results = []
    
    for i, file in enumerate(processed_files):
        status.markdown(f"**Grading:** `{file.name}`...")
        time.sleep(2) 
        feedback = grade_submission(file, user_model_id) 
        score = parse_score(feedback)
        new_results.append({"Filename": file.name, "Score": score, "Feedback": feedback})
        progress.progress((i + 1) / len(processed_files))
        
    st.session_state.current_results = new_results
    status.success("✅ Grading Complete! Scrolling down...")
    progress.empty()

# --- 8. PERSISTENT DISPLAY ---
if st.session_state.current_results:
     display_results_ui()