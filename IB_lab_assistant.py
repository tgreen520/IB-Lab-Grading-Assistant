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
    page_title="IB Lab Grader", 
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
- REQUIRED DETAILS:
  * Units for Independent Variable (IV) and Dependent Variable (DV) must be included.
  * Method of measuring the DV must be explicitly stated.
  * DV must be specific and measurable (not vague).
- DEDUCTIONS:
  * Missing units for IV/DV: -0.5 pts.
  * DV measurement is vague or measurement method is missing: -1.0 pt.

4. VARIABLES (10 pts):
- Criteria: IV, DV, 3+ Controls.
- SCORING: 
  * 10/10: All defined + explanations.
  * 9.5/10: DV measurement vague (-0.5).
  * 9.0/10: Explanations missing (-1.0).
  - DEDUCTIONS:
  * Control variables missing (fewer than 3): -4.0
  * EXCEPTION: If the student lists specific instances (e.g. "Mass of Zinc", "Mass of Mg") as multiple IVs, do NOT deduct 4 points. Deduct ONLY 1.0 point for "Categorization Error".
  * Control variables not justified: -1.0
  * Description of control variables vague: -1.0
  * Independent variable not thoroughly explained: -1.0
  * Dependent variable not thoroughly explained: -1.0
  * Do not deduct points for multiple independent variables if they are derived (e.g. Temp vs 1/Temp).
  * Do not deduct for dependent variables that are derived units. 
  * DV measurement vague: -0.5

5. PROCEDURES & MATERIALS (10 pts):
- Criteria: Numbered steps, quantities, safety, diagram.
- UNCERTAINTIES & PRECISION:
  * Uncertainties SHOULD be listed in the Materials section.
  * **SCORING:**
    - Listed in Materials: 0 Deduction.
    - Missing in Materials BUT listed in Data Section: -0.5 pts.
    - Completely missing (not in Materials OR Data): -1.0 pt.
  * Precision mismatch (uncertainty vs. measurement): -0.5 pts.
  * Diagram or photograph missing: -0.5 pt.

6. RAW DATA (10 pts):
- Criteria: Qualitative observations, tables, units, sig figs.
- REQUIREMENT: Uncertainties must be reported in Data Tables (headers or cells).

7. DATA ANALYSIS (10 pts):
- UNCERTAINTY PROPAGATION (IB CHEMISTRY STANDARD):
  * MUST use Absolute Uncertainty (for + / -) and Percentage Uncertainty (for * / /).
  * NOTE: Intermediate steps are NOT required. Do NOT deduct for missing intermediate steps if the result is correct.
  * **SCORING:**
    - **Attempted (Partial):** Any calculation (e.g., standard deviation, range) OR propagation attempted, even if incomplete/incorrect: -1.0 pt.
    - **Missing:** No attempt at calculation or propagation: -2.0 pts.
- GRAPHS (Bar or Scatter allowed based on context):
  * Graph Missing: -2.0 pts. (NOTE: If Graph is missing, do NOT deduct for missing axis labels or missing averages. Max deduction is -2.0).
  * Graph Present but Axis labels/Units missing: -1.0 pt.
  * MULTIPLE TRIALS RULE: If >1 trial performed, graph MUST show AVERAGES. (If missing: -2.0 pts).
  * SCATTER PLOT REQ: Trendline, Equation, R^2 (if applicable). 
  * BAR GRAPH REQ: Average values shown.

8. CONCLUSION (10 pts) [STRICT DEDUCTIONS]:
- UNCERTAINTY IMPACT (CROSS-CHECK EVALUATION): 
  * Check BOTH Conclusion and Evaluation.
  * **Full Discussion:** Impact on data explained in either section: 0 deduction.
  * **Partial Discussion:** Uncertainty mentioned (in Conc or Eval), but specific impact on data is NOT explained: -1.0 pt.
  * **Missing:** No mention of uncertainty in Conclusion OR Evaluation: -2.0 pts.
- LITERATURE COMPARISON:
  * Must compare results to published literature/accepted values to support or refute findings.
  * If missing: -1.0 pt.
- IV/DV RELATIONSHIP: Must explain graph trend. (If poor: -1.0)
- THEORY: Connect to chemical theory.
  * Explained fully: 0 deduction.
  * Discussed but incomplete explanation: -1.0 pt.
  * Completely missing: -2.0 pts.
- QUANTITATIVE SUPPORT: 
  * Must cite collected raw data specific numbers.
  * If only DERIVED data (averages, rates, R^2) is discussed but collected data is missing: -1.0 pt.
  * If NO quantitative data (neither derived nor collected) is cited: -2.0 pts.
- QUALITATIVE SUPPORT: Must cite observations. (If missing: -0.5)
- STATISTICS: Explain R and R^2 (if Scatter used). (If missing: -2.0. If partially explained: -1.0)

9. EVALUATION (10 pts) [STRICT QUALITY GATES]:
- REQUIREMENT: List errors + Specific Directional Impact + Specific Improvement.
- ERROR CLASSIFICATION: Must differentiate between systematic and random errors. (Not done: -0.5).
- IMPACT SCORING:
  * Impact defined for 100% of errors = 2 pts.
  * Impact defined for SOME (not all) errors = 1 pt (Deduct 1.0).
  * No impact defined = 0 pts (Deduct 2.0).
- IMPROVEMENT SCORING:
  * Specific equipment named = 2 pts.
  * Vague ("use better scale") = 1.5 pts (Deduct 0.5).
  * Generic ("be careful") = 0 pts (Deduct 2.0).

10. REFERENCES (10 pts):
- Criteria: Citations present for all external data/images.
- SCORING:
  * 10/10: References are present (any style).
  - DEDUCTIONS:
  * References completely missing: -2.0
  * Citations missing for specific data/images: -1.0
  * STRICT EXCEPTION: Do NOT deduct points for minor formatting errors (e.g. missing italics, wrong comma placement, APA vs MLA). If the link/source is there, give full points.

# --- 4. SYSTEM PROMPT (UPGRADED FOR THOROUGHNESS) ---
SYSTEM_PROMPT = """You are an expert IB Chemistry Lab Grader and Educator. 
Your goal is not just to grade, but to **teach** the student how to improve by referencing specific IB criteria.

### 🧪 SCIENTIFIC FORMATTING RULES (STRICT):
1.  **NO HTML or LATEX TAGS:** Do not use `<sup>`, `<sub>`, `$`, or markdown code blocks for chemistry.

### 🧪 YOUR OUTPUT FORMATTING (SCIENTIFIC):
1.  **USE UNICODE CHARACTERS:** Even if the student's text looks flat ("cm3"), YOUR feedback must use proper symbols.
    * *Bad:* cm^3, dm^-3, CO_2
    * *Good:* cm³, dm⁻³, CO₂, 10⁵, ±0.05
    * *Common Symbols:* ⁰ ¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹ ⁺ ⁻ ₀ ₁ ₂ ₃ ₄ ₅ ₆ ₇ ₈ ₉
2.  **NO FALSE ACCUSATIONS:** Do **NOT** accuse the student of using HTML tags (like `<sup>`) or LaTeX. The student is writing in Word; they are not coding. If the text looks weird, blame the PDF extractor, not the student.

### 🛡️ VOCABULARY & PHRASING IMMUNITY (DO NOT DEDUCT):
1.  **"HCl Acid" / "H₂SO₄ Acid":** While technically redundant (since "acid" is implied), this is a common student shorthand.
    * **Action:** Do NOT deduct points. Do NOT mention it as an error. Treat it as correct phrasing.
2.  **"Molar Mass of X":** If they say "Molecular Weight" instead of "Molar Mass," accept it.
3.  **"Experiment" vs "Investigation":** Use these interchangeably.

### 🧠 DEEP DIVE FEEDBACK PROTOCOL (MANDATORY):

1.  **THE "RULE + EVIDENCE" STANDARD:**
    * **Never** make a claim without citing the Rubric Section.
    * *Bad:* "You need more controls."
    * *Good:* "❌ **Rubric Section 4 (Variables)** requires at least 3 controlled variables to ensure a fair test. You only listed 1."

2.  **STRENGTHS = "QUOTE + CRITERIA + EFFECT":**
    * Do not just praise. You must explain **why** it was effective scientifically.
    * **Structure:** [Quote the student] -> [Cite the specific Rubric Criteria met] -> [Explain the scientific value].
    * *Example:* "✅ You successfully stated 'The uncertainty of the burette is ±0.05mL.' This meets the **Section 5 (Precision)** requirement. Listing this allows us to propagate error correctly in the analysis."

3.  **IMPROVEMENTS = "ERROR + RULE + FIX + EDUCATIONAL REASON":**
    * **The Error:** Quote exactly what they wrote (or state 'Completely Missing').
    * **The Rule:** Start with **"The rubric requires..."** (Do **NOT** mention specific Section numbers like 'Section 2').
    * **The Fix:** Provide a concrete, corrected example using UNICODE.
    * **The Educational Reason:** Explain *why* this rule exists in Chemistry.
    * *Example:* "⚠️ **Error:** You wrote units as 'mol/dm3'. **Rule:** The rubric requires inverse notation. **Fix:** Write 'mol dm⁻³'. **Why?** This is the standard IUPAC notation."

### ⚖️ CALIBRATION & TIE-BREAKER STANDARDS:

1.  **THE "BENEFIT OF DOUBT" RULE:**
    * If a student's phrasing is clumsy but technically accurate -> **NO DEDUCTION.**
    * If a student uses the wrong vocabulary word but the concept is correct -> **-0.5 (Vague).**
    * If the text is contradictory (says X, then says Not X) -> **-1.0 (Unclear).**

2.  **THE "STRICT BINARY" DECISION TREE:**
    * **Is the Hypothesis Justification missing?** * YES -> -2.0.
        * NO, but it relies on non-scientific reasoning (e.g., "I feel like...") -> -1.0.
    * **Is the R² value on the graph?**
        * YES (Explicitly written) -> 0 deduction.
        * NO (Not visible) -> -1.0 deduction. (Do not assume it is "implied").

### 🧠 SCORING ALGORITHMS (STRICT ENFORCEMENT):

1.  **HIDDEN MATH (CRITICAL):**
    * You MUST perform your score calculations inside a special block: `<<<MATH: 10.0 - 0.5 = 9.5>>>`.
    * This block must appear **immediately before** the section header.
    * You MUST list every specific deduction in this block to ensure the subtraction is correct.

2.  **HYPOTHESIS (Section 3) - SPECIFICITY & UNITS:**
    * **Check for Units:** Did they state the units for the IV and DV? (e.g., "Temperature (°C)"). If missing -> **Deduct 0.5**.
    * **Check Measurement Method:** Did they say *how* they will measure the DV? (e.g., "using a stopwatch"). If vague or missing -> **Deduct 1.0**.

3.  **MATERIALS (Section 5) - UNCERTAINTY LOCATION:**
    * **Check Materials List:** Are uncertainties listed (e.g., ±0.05)? If YES -> **0 Deduction**.
    * **Check Data Section:** If missing in Materials, are they in the Data Tables?
        * YES (In Data, Missing in Materials) -> **Deduct 0.5**.
        * NO (Missing Everywhere) -> **Deduct 1.0**.

4.  **DATA ANALYSIS (Section 7) - UNCERTAINTY ATTEMPT RULE:**
    * **Attempted:** If there is ANY uncertainty math (e.g., they listed instrument error, calculated standard deviation, OR tried to propagate), but it is incomplete/incorrect -> **Deduct 1.0**.
    * **Missing:** Only deduct **2.0** if there is ABSOLUTELY NO uncertainty calculation or propagation found.

5.  **CONCLUSION (Section 8) - CROSS-CHECK LOGIC:**
    * **Uncertainty Impact:** Check BOTH Conclusion and Evaluation.
        * **Discussion + Specific Impact Explained:** 0 Deduction.
        * **Discussion Present + Impact Missing:** If they mention uncertainty in either section, but fail to explain the specific impact on the data -> **Deduct 1.0**.
        * **No Discussion:** If NO mention of uncertainty in EITHER section -> **Deduct 2.0**.

### OUTPUT FORMAT (STRICTLY FOLLOW THIS STRUCTURE):

# 📝 SCORE: [Total Points]/100
STUDENT: [Filename]

**📊 OVERALL SUMMARY:**
* [1-2 sentences summarizing the scientific quality of the report]
* [Specific comment on the quality of the graphs/data presentation]

**📋 DETAILED RUBRIC BREAKDOWN:**

<<<MATH: ...>>>
**1. FORMATTING: [Score]/10**
* **✅ Strengths:** [Detailed explanation of tone/voice quality]
* **⚠️ Improvements:** [**MANDATORY:** "Found [X] subscript errors." (If X=1 or 2, Score **MUST** be 9.5. If X>=3, Score is 9.0 or lower).]

<<<MATH: ...>>>
**2. INTRODUCTION: [Score]/10**
* **✅ Strengths:** [Example: "You explicitly stated the objective: 'To determine the activation energy...' (Section 2). This provides a clear focus for the experiment."]
* **⚠️ Improvements:** [Example: "Error: No background theory. Rule: Section 2 requires 'background theory and balanced equations.' Fix: Add a paragraph explaining Collision Theory and the equation 2H2O2 -> 2H2O + O2." [**CRITICAL CHECKS:** * "Objective explicit?" (-1.0 if No, -0.5 if Vague). * "Chemical Equation present?" (-1.0 if No). * "Background thoroughly explained?" (-1.0 if No, -0.5 if Brief or not connected to objective). NOTE: Do not penalize citation context or unit consistency.]]

<<<MATH: ...>>>
**3. HYPOTHESIS: [Score]/10**
* **✅ Strengths:** [Quote prediction and praise the scientific reasoning]
* **⚠️ Improvements:** [**CRITICAL CHECKS:**
* "Justification: [Present/Missing/Vague]" (-2.0 if missing, -1.0 if vague/incomplete).
* "Units for IV/DV: [Present/Missing]" (-1.0 if missing, -0.5 if partial).
* "DV Measurement Description: [Specific/Vague/Missing]" (-1.0 if missing, -0.5 if vague).]

<<<MATH: ...>>>
**4. VARIABLES: [Score]/10**
* **✅ Strengths:** [Quote a well-controlled variable.]
* **⚠️ Improvements:** [Check Explanations. If missing, explain WHY that variable affects the reaction.]

<<<MATH: ...>>>
**5. PROCEDURES & MATERIALS: [Score]/10**
* **✅ Strengths:** [Quote safety/precision details.]
* **⚠️ Improvements:** [Check Uncertainties. If missing, provide an example: 'Beaker (±5mL)'.]

<<<MATH: ...>>>
**6. RAW DATA: [Score]/10**
* **✅ Strengths:** [Quote qualitative observations.]
* **⚠️ Improvements:** [Check Sig Figs. Explain why precision must match uncertainty.]

<<<MATH: ...>>>
**7. DATA ANALYSIS: [Score]/10**
* **✅ Strengths:** [Summarize the calculation process. If Graph is perfect, mention that the scatterplot, equation, and labels are all correct here.]
* **⚠️ Improvements:** [**GRAPH AUDIT:** "Trendline Equation: [Present/Missing]" (-1.0 if missing). "R² Value: [Present/Missing]" (-1.0 if missing). Propagation of uncertainty in measurements and calculations. [Present/Missing]" (-2.0 if missing. -1.0 if partial or incorrect.]
**CALCULATION AUDIT:** "Example calculations were [Clear/Unclear]." (If unclear, -1.0 pts). "Calculation steps were [Clearly Explained/Not Labeled or Explained]." (If not labeled/explained, -0.5 pts).]

<<<MATH: ...>>>
**8. CONCLUSION: [Score]/10**
* **✅ Strengths:** [Quote data used to support the claim]
* **⚠️ Improvements:** [**CRITICAL CHECKS:** Summarize missing elements naturally. Ensure you comment on:
  1. **Hypothesis Support** (-1.0 if not stated)
  2. **Outliers/Omissions** (-1.0 if not addressed, -0.5 if vague)
  3. IV/DV Relationship (-1.0)
  4. Chemical Theory (-1.0)
  5. Quantitative Support (-2.0)
  6. Qualitative Support (-0.5)
  7. **Literature Comparison** (-0.5 if vague)
  8. **R and R² Explanation** (-1.0 if R missing, -1.0 if R² missing, -0.5 if R² vague)]

<<<MATH: ...>>>
**9. EVALUATION: [Score]/10**
* **✅ Strengths:** [**LIST:** "You identified: [Error 1], [Error 2]..." and comment on depth.]
* **⚠️ Improvements:** [**ERROR CLASSIFICATION:** "You did not differentiate between systematic and random errors. (-0.5 pt)" OR "You successfully distinguished systematic from random errors."
**IMPACT/IMPROVEMENT AUDIT:** * "You listed [X] errors but only provided specific directional impacts for [Y] of them. (-1 pt)"
  * "Improvements were listed but were slightly vague (e.g., did not name specific equipment). (-0.5 pt)" ]

<<<MATH: ...>>>
**10. REFERENCES: [Score]/10**
* **✅ Strengths:** [Comment on source credibility.]
* **⚠️ Improvements:** [Formatting check.]

**💡 TOP 3 EDUCATIONAL PRIORITIES:**
1.  [Specific concept to review, e.g., "Review Propagation of Uncertainty formulas"]
2.  [Specific lab technique to improve]
3.  [Specific writing focus]
"""

# Initialize Session State
if 'saved_sessions' not in st.session_state:
    st.session_state.saved_sessions = {}
if 'current_results' not in st.session_state:
    st.session_state.current_results = []
if 'current_session_name' not in st.session_state:
    st.session_state.current_session_name = "New Grading Session"
if 'autosave_dir' not in st.session_state:
    st.session_state.autosave_dir = "autosave_feedback_ib"

client = anthropic.Anthropic(api_key=API_KEY)

# --- CREATE AUTOSAVE DIRECTORY ---
os.makedirs(st.session_state.autosave_dir, exist_ok=True)

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

# --- NEW FUNCTION: AUTOSAVE INDIVIDUAL REPORT ---
def autosave_report(item, autosave_dir):
    """Save individual report as Word doc and append to CSV immediately after grading."""
    try:
        # 1. Save Word Document
        doc = Document()
        write_markdown_to_docx(doc, item['Feedback'])
        safe_filename = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
        doc_path = os.path.join(autosave_dir, safe_filename)
        doc.save(doc_path)
        
        # 2. Append to CSV (or create if doesn't exist)
        csv_path = os.path.join(autosave_dir, "gradebook.csv")
        
        # Parse feedback into row data
        row_data = {
            "Filename": item['Filename'],
            "Overall Score": item['Score']
        }
        feedback_data = parse_feedback_for_csv(item['Feedback'])
        row_data.update(feedback_data)
        
        # Check if CSV exists
        if os.path.exists(csv_path):
            existing_df = pd.read_csv(csv_path)
            # Remove duplicate if re-grading same file
            existing_df = existing_df[existing_df['Filename'] != item['Filename']]
            new_df = pd.concat([existing_df, pd.DataFrame([row_data])], ignore_index=True)
        else:
            new_df = pd.DataFrame([row_data])
        
        new_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        return True
    except Exception as e:
        print(f"Autosave failed for {item['Filename']}: {e}")
        return False

def grade_submission(file, model_id):
    ext = file.name.split('.')[-1].lower()
    
    # Updated Prompt Construction for Educational Depth
    user_instructions = (
        "Please grade this lab report based on the provided rubric.\n"
        "🚨 **INSTRUCTION FOR FEEDBACK DEPTH:**\n"
        "1. **BE SPECIFIC:** Do not be vague. If you deduct points, you must explain exactly **WHY**.\n"
        "2. **BE EDUCATIONAL:** Explain the scientific reason behind the rules.\n"
        "3. **PHRASING:** When citing rules, simply say **'The rubric requires...'**. Do NOT cite specific section numbers (e.g. do NOT say 'Section 4 requires...').\n"
        "\n⚠️ **CRITICAL RUBRIC UPDATES TO ENFORCE:**\n"
        "4. **FORMATTING:** \n"
        "   - **Redundancy:** Do NOT deduct for terms like 'HCl acid' or 'Na salt'. Ignore this redundancy completely.\n"
        "1. **MATERIALS:** Look for uncertainty values (±). If missing in Materials but present in Data -> -0.5 only.\n"
        "2. **DATA ANALYSIS:** \n"
        "   - **Attempt Rule:** If they attempted ANY uncertainty math (even if wrong) -> Deduct 1.0. Only deduct 2.0 if completely missing.\n"
        "   - **Derived Independent Variables:** If they list 'Temp' and '1/Temp' as two IVs, this is CORRECT. Do not deduct.\n"
        "3. **VARIABLES:** \n"
        "   - **Categorization Error:** If they list specific instances (e.g. Zinc, Mg) instead of a category (Type of Metal) -> Deduct 1.0 (Categorization), NOT 4.0 (Missing Controls).\n"
        "   - **Derived Independent Variables:** Do NOT deduct points if the student lists multiple Independent Variables where the extra ones are mathematically derived from the main IV (e.g., 'Temperature' and '1/Temperature', or 'Concentration' and 'Natural Log of Concentration'). Treat this as a single, valid IV setup.\n"
        "   - **Derived Dependent Variables:** Do NOT deduct points if the student lists multiple Dependent Variables where the extra ones are mathematically derived from the main IV (e.g., 'Temperature' and '1/Temperature', or 'Concentration' and 'Natural Log of Concentration'). Treat this as a single, valid IV setup.\n"
        "   - **Misidentified IVs (Categorization Error):** If a student lists specific instances (e.g., 'Mass of Magnesium', 'Mass of Zinc') as multiple Independent Variables instead of the general category (e.g., 'Type of Metal'), deduct **ONLY 1.0 point** for 'Improper Variable Classification'. Do **NOT** deduct 4.0 points. Do **NOT** treat this as 'Missing Control Variables'.\n"
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
# --- WORD FORMATTER (Strict Symbol Cleaning) ---
def write_markdown_to_docx(doc, text):
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue # SKIP EMPTY LINES FOR CONTINUOUS FLOW
        
        # 1. Handle Score Header & Student Name (Larger - Level 2)
        if line.startswith('# ') or line.startswith('STUDENT:'): 
            clean = line.replace('# ', '').replace('*', '').strip()
            # Changed from Level 4 (Small) to Level 2 (Large)
            doc.add_heading(clean, level=2) 
            continue
        
        # 2. Handle H3 (### ) - CLEANED
        if line.startswith('### '):
            clean = line.replace('### ', '').replace('*', '').strip()
            doc.add_heading(clean, level=3)
            continue
        
        # 3. Handle H2 (## ) - CLEANED
        if line.startswith('## '): 
            clean = line.replace('## ', '').replace('*', '').strip()
            doc.add_heading(clean, level=2)
            continue
        
        # 4. REMOVE SEPARATORS
        if line.startswith('---') or line.startswith('___'):
            continue

        # 5. Handle Bullets (* or -) - CLEANED
        if line.startswith('* ') or line.startswith('- '):
            p = doc.add_paragraph(style='List Bullet')
            content = line[2:] 
        else:
            p = doc.add_paragraph()
            content = line

        # 6. Handle Bold (**text**) - CLEANED
        parts = re.split(r'(\*\*.*?\*\*)', content)
        for part in parts:
            if part.startswith('**') and part.endswith('**'):
                clean_text = part[2:-2].replace('*', '') # Strip any lingering asterisks
                run = p.add_run(clean_text)
                run.bold = True
            else:
                p.add_run(part.replace('*', '')) # Strip lingering asterisks

def create_master_doc(results, session_name):
    doc = Document()
    # REMOVED SESSION HEADER
    # doc.add_heading(f"Lab Report Grades: {session_name}", 0) 
    for item in results:
        # REMOVED FILENAME HEADER (Starts with Score + Student Name)
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
            # REMOVED FEEDBACK HEADER
            write_markdown_to_docx(doc, item['Feedback'])
            doc_buffer = BytesIO()
            doc.save(doc_buffer)
            safe_name = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
            z.writestr(safe_name, doc_buffer.getvalue())
    return zip_buffer.getvalue()

# --- NEW: AUTOSAVE INDIVIDUAL REPORT ---
def autosave_report(item, autosave_dir):
    """Save individual report as Word doc and append to CSV immediately after grading."""
    try:
        # 1. Save Word Document
        doc = Document()
        write_markdown_to_docx(doc, item['Feedback'])
        safe_filename = os.path.splitext(item['Filename'])[0] + "_Feedback.docx"
        doc_path = os.path.join(autosave_dir, safe_filename)
        doc.save(doc_path)
        
        # 2. Append to CSV (or create if doesn't exist)
        csv_path = os.path.join(autosave_dir, "gradebook.csv")
        
        # Parse feedback into row data
        row_data = {
            "Filename": item['Filename'],
            "Overall Score": item['Score']
        }
        feedback_data = parse_feedback_for_csv(item['Feedback'])
        row_data.update(feedback_data)
        
        # Check if CSV exists
        if os.path.exists(csv_path):
            existing_df = pd.read_csv(csv_path)
            # Remove duplicate if re-grading same file
            existing_df = existing_df[existing_df['Filename'] != item['Filename']]
            new_df = pd.concat([existing_df, pd.DataFrame([row_data])], ignore_index=True)
        else:
            new_df = pd.DataFrame([row_data])
        
        new_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        return True
    except Exception as e:
        print(f"Autosave failed for {item['Filename']}: {e}")
        return False

def display_results_ui():
    if not st.session_state.current_results:
        return

    st.divider()
    st.subheader(f"📊 Results: {st.session_state.current_session_name}")
    
    # --- EXPANDED CSV LOGIC WITH SORTING ---
    results_list = []
    for item in st.session_state.current_results:
        row_data = {
            "Filename": item['Filename'],
            "Overall Score": item['Score']
        }
        feedback_data = parse_feedback_for_csv(item['Feedback'])
        row_data.update(feedback_data)
        results_list.append(row_data)
        
    csv_df = pd.DataFrame(results_list)
    
    # Sort columns to put Filename/Score/Summary first
    cols = list(csv_df.columns)
    priority = ['Filename', 'Overall Score', 'Overall Summary']
    remaining = [c for c in cols if c not in priority]
    # Simple logic to keep section score/feedback adjacent
    remaining.sort(key=lambda x: (x.split(' ')[0], 'Feedback' in x)) 
    
    final_cols = [c for c in priority if c in cols] + remaining
    csv_df = csv_df[final_cols]
    
    csv_data = csv_df.to_csv(index=False).encode('utf-8-sig') 
    
    master_doc_data = create_master_doc(st.session_state.current_results, st.session_state.current_session_name)
    zip_data = create_zip_bundle(st.session_state.current_results)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("📄 Google Docs Compatible (.docx)", master_doc_data, f'{st.session_state.current_session_name}_Docs.docx', "application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)
        st.caption("Upload to Drive -> Open as Google Doc")
    with col2:
        st.download_button("📦 Student Bundle (.zip)", zip_data, f'{st.session_state.current_session_name}_Students.zip', "application/zip", use_container_width=True)
    with col3:
        st.download_button("📊 Detailed CSV Export", csv_data, f'{st.session_state.current_session_name}_Detailed.csv', "text/csv", use_container_width=True)
        st.caption("Includes separate columns for every section score and comment.")

    # --- NEW: AUTOSAVE FOLDER ACCESS ---
    st.divider()
    st.info("💾 **Auto-saved files:** Individual feedback documents and gradebook are being saved to the `autosave_feedback` folder as grading progresses.")
    
    autosave_path = st.session_state.autosave_dir
    if os.path.exists(autosave_path):
        csv_autosave = os.path.join(autosave_path, "gradebook.csv")
        if os.path.exists(csv_autosave):
            with open(csv_autosave, 'rb') as f:
                st.download_button(
                    "📥 Download Auto-saved Gradebook (CSV)",
                    f.read(),
                    "autosaved_gradebook.csv",
                    "text/csv",
                    use_container_width=True
                )
        
        # Create zip of all autosaved Word docs
        autosave_files = [f for f in os.listdir(autosave_path) if f.endswith('.docx')]
        if autosave_files:
            zip_autosave = BytesIO()
            with zipfile.ZipFile(zip_autosave, 'w', zipfile.ZIP_DEFLATED) as z:
                for filename in autosave_files:
                    file_path = os.path.join(autosave_path, filename)
                    z.write(file_path, filename)
            
            st.download_button(
                "📥 Download All Auto-saved Word Docs (.zip)",
                zip_autosave.getvalue(),
                "autosaved_feedback.zip",
                "application/zip",
                use_container_width=True
            )

    # 1. Show the Gradebook Table
    st.write("### 🏆 Gradebook")
    st.dataframe(csv_df, use_container_width=True)
    
    # 2. Show the Feedback (Stacked directly below, no hiding!)
    st.write("### 📝 Detailed Feedback History")
    
    # We use reversed() so the newest file is always at the top
    for item in reversed(st.session_state.current_results):
        with st.expander(f"📄 {item['Filename']} (Score: {item['Score']})"):
            st.markdown(item['Feedback'])

# --- 6. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # UPDATED DEFAULT MODEL ID
    user_model_id = st.text_input(
        "🤖 Model ID", 
        value="claude-sonnet-4-20250514", 
        help="Change this if you have a specific Beta model or newer ID"
    )
    
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
        # CHANGED FROM st.text(PRE_IB_RUBRIC) TO st.text(IB_RUBRIC)
        st.text(IB_RUBRIC)

# --- 7. MAIN INTERFACE ---
st.title("🧪 IB Lab Grader")
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
            st.warning(f"⚠️ {counts['ignored']} files were ignored (unsupported format).")
    else:
        if raw_files:
            st.warning("No valid PDF, Word, or Image files found.")

if st.button("🚀 Grade Reports", type="primary", disabled=not processed_files):
    
    st.write("---")
    progress = st.progress(0)
    status_text = st.empty()
    live_results_table = st.empty()
    
    # NEW: Placeholder for cumulative feedback display (cleared and rewritten each iteration)
    st.subheader("📋 Live Grading Feedback")
    feedback_placeholder = st.empty()
    
    # Initialize Session State list if not present
    if 'current_results' not in st.session_state:
        st.session_state.current_results = []
    
    # Create a set of already graded filenames for quick lookup
    existing_filenames = {item['Filename'] for item in st.session_state.current_results}
    
    for i, file in enumerate(processed_files):
        # 1. SMART RESUME CHECK: Skip if already graded
        if file.name in existing_filenames:
            status_text.info(f"↩ Skipping **{file.name}** (Already Graded)")
            time.sleep(0.5) # Brief pause for visual feedback
            progress.progress((i + 1) / len(processed_files))
            continue

        # 2. GRADING LOGIC
        status_text.markdown(f"**Grading:** `{file.name}` ({i+1}/{len(processed_files)})...")
        
        try:
            # Polite delay to prevent API overloading
            time.sleep(2) 
            
            feedback = grade_submission(file, user_model_id) # PASSING USER MODEL ID
            score = parse_score(feedback)
            
            # 3. IMMEDIATE SAVE TO SESSION STATE
            new_entry = {
                "Filename": file.name,
                "Score": score,
                "Feedback": feedback
            }
            
            st.session_state.current_results.append(new_entry)
            
            # 4. AUTOSAVE TO DISK (NEW - CRITICAL FOR RECOVERY)
            autosave_success = autosave_report(new_entry, st.session_state.autosave_dir)
            if autosave_success:
                status_text.success(f"✅ **{file.name}** graded & auto-saved! (Score: {score}/100)")
            else:
                status_text.warning(f"⚠️ **{file.name}** graded but autosave failed (Score: {score}/100)")
            
            # Update the existing set so duplicates within the same batch run are also caught
            existing_filenames.add(file.name)
            
            # 5. LIVE TABLE UPDATE
            df_live = pd.DataFrame(st.session_state.current_results)
            live_results_table.dataframe(df_live[["Filename", "Score"]], use_container_width=True)
            
            # 6. UPDATED: SINGLE COPY CUMULATIVE FEEDBACK DISPLAY
            # Clear and rewrite the entire feedback section to avoid duplicates
            with feedback_placeholder.container():
                for idx, item in enumerate(st.session_state.current_results):
                    # Start expanded for most recent, collapsed for older ones
                    is_most_recent = (idx == len(st.session_state.current_results) - 1)
                    with st.expander(f"📄 {item['Filename']} (Score: {item['Score']}/100)", expanded=is_most_recent):
                        st.markdown(item['Feedback'])
            
        except Exception as e:
            st.error(f"❌ Error grading {file.name}: {e}")
            
        progress.progress((i + 1) / len(processed_files))
        

    status_text.success("✅ Grading Complete! All reports auto-saved.")
    progress.empty()
    
    # Show message about autosave location
    st.info(f"💾 **Backup Location:** All feedback has been saved to `{st.session_state.autosave_dir}/` folder. You can download individual files or the full gradebook below.")

# --- 8. PERSISTENT DISPLAY ---
if st.session_state.current_results:
    display_results_ui()