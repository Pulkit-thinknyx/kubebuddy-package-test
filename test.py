from kubernetes import client, config
import yaml
import time 
from fpdf import FPDF
import codecs
import re
import time
import codecs
from datetime import datetime

def run_kube_bench_job():
    config.load_kube_config()  # or load_incluster_config() if inside a pod

    with open("job.yaml", "r") as f:
        job_yaml = yaml.safe_load(f)

    batch_v1 = client.BatchV1Api()
    namespace = "default"

    try:
        batch_v1.create_namespaced_job(body=job_yaml, namespace=namespace)
        print("✅ Kube-bench Job submitted.")
    except client.rest.ApiException as e:
        print(f"❌ Failed to create job: {e}")

def get_kube_bench_logs(job_name="kube-bench", namespace="default"):
    core_v1 = client.CoreV1Api()

    # Wait for pod to be ready
    pods = []
    while not pods:
        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector="job-name=" + job_name
        ).items
        time.sleep(1)

    pod_name = pods[0].metadata.name

    # Wait until it's done running
    while pods[0].status.phase not in ("Succeeded", "Failed"):
        time.sleep(2)
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector="job-name=" + job_name).items

    log_output = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
    return log_output

def generate_kube_bench_pdf(raw_output, filename="kube_bench_report.pdf"):
    raw_output = codecs.decode(raw_output, 'unicode_escape')
    
    # Clean up problematic characters
    replacements = {
        ''': "'", ''': "'", '"': '"', '"': '"',
        '\t': '    ',  # Replace tabs with spaces
        '\x80': '', '\x98': '', '\x99': '',
    }
    for bad, good in replacements.items():
        raw_output = raw_output.replace(bad, good)

    # Parse sections from raw output
    sections = parse_kube_bench_output(raw_output)

    # Initialize PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Add Unicode font
    pdf.add_font('Dejavu_Sans', '', 'DejaVuSans.ttf')
    pdf.add_font('Dejavu_Sans', 'B', 'DejaVuSans-Bold.ttf')

    # Add title and date
    pdf.set_font('Dejavu_Sans', 'B', 16)
    pdf.cell(0, 10, 'Kubernetes CIS Benchmark Report', 0, align='C')
    pdf.ln(10)
    pdf.set_font('Dejavu_Sans', '', 10)
    pdf.cell(0, 5, f'Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', 0, align='C')
    pdf.ln(5)

    # Mapping of section numbers to summary section names
    summary_map = {
        "1": "== Summary master ==",
        "2": "== Summary etcd ==",
        "3": "== Summary controlplane ==",
        "4": "== Summary node ==",
        "5": "== Summary policies ==",
    }

    # Render Summary Total at the start
    if "== Summary total ==" in sections:
        render_summary_section(pdf, sections["== Summary total =="], "== Summary total ==")

    # Render sections grouped with their summaries
    for section_num in ["1", "2", "3", "4", "5"]:
        # Render main section and subsections
        for section_name, section_content in sections.items():
            if section_name.startswith(section_num + " ") or section_name.startswith(section_num + "."):
                render_section(pdf, section_name, section_content)

        # Render the summary for the section
        summary_name = summary_map.get(section_num)
        if summary_name and summary_name in sections:
            render_summary_section(pdf, sections[summary_name], summary_name)

    # Save PDF
    pdf.output(filename)
    print(f"✅ PDF saved to {filename}")


def parse_kube_bench_output(raw_output):
    """Parse kube-bench output into sections"""
    sections = {}
    
    # Extract summary sections (which start with '== Summary' and end with '==' or next section)
    summary_pattern = r'== Summary .+? ==\n(.*?)\n\n'
    for match in re.finditer(summary_pattern, raw_output, re.DOTALL):
        section_name = match.group(0).split('\n')[0].strip()  # Extract the full summary title (e.g., '== Summary etcd ==')
        content = match.group(1).strip()
        sections[section_name] = content

    # Extract other sections (non-summary)
    section_pattern = r'\[INFO\]\s+([\d\.\s]+.*?)(?=\[INFO\]|\Z)'
    for match in re.finditer(section_pattern, raw_output, re.DOTALL):
        section_text = match.group(1).strip()
        if section_text:
            title = section_text.split('\n')[0].strip()
            content = '\n'.join(section_text.split('\n')[1:]).strip()
            sections[title] = content

    return sections

def render_summary_section(pdf, summary_text, summary_title):
    """Render the summary section with a professional-looking table and colorful status indicators"""
    from fpdf import XPos, YPos
    
    summary_title = summary_title.strip('= ').strip()

    pdf.set_font('Dejavu_Sans', 'B', 12)
    pdf.cell(0, 10, summary_title, 0, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align='L')
    pdf.set_font('Dejavu_Sans', '', 10)
    
    # Create table headers
    pdf.set_fill_color(240, 240, 240)  # Light gray background for header
    pdf.cell(40, 8, 'Status', 1, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C', fill=1)
    pdf.cell(30, 8, 'Count', 1, new_x=XPos.LMARGIN, new_y=YPos.TOP, align='C', fill=1)
    pdf.ln(8)  # Move to the next line after header

    # Parse the summary text and fill the table
    for line in summary_text.split('\n'):
        if re.search(r'PASS|FAIL|WARN|INFO', line):
            status = re.search(r'(PASS|FAIL|WARN|INFO)', line).group(1)
            count = re.search(r'(\d+)', line).group(1)
            
            # Set color based on status
            if status == 'PASS':
                pdf.set_text_color(0, 128, 0)  # Green
            elif status == 'FAIL':
                pdf.set_text_color(255, 0, 0)  # Red
            elif status == 'WARN':
                pdf.set_text_color(255, 165, 0)  # Orange
            else:
                pdf.set_text_color(0, 0, 0)  # Black
            
            # Add row data
            pdf.cell(40, 8, status, 1, new_x=XPos.RIGHT, new_y=YPos.TOP, align='C')
            pdf.cell(30, 8, count, 1, new_x=XPos.LMARGIN, new_y=YPos.TOP, align='C')
            pdf.ln(8)  # New line for the next row
            
            pdf.set_text_color(0, 0, 0)  # Reset to black after the row
    
    pdf.ln(5)  # Add extra space after the table

def render_section(pdf, section_name, section_content):
    """Render a section or subsection with formatting"""
    from fpdf import XPos, YPos

    # Determine if it's a subsection
    is_subsection = '.' in section_name.split(' ')[0]

    # Section or subsection header styling
    if is_subsection:
        pdf.set_font('Dejavu_Sans', '', 11)   # smaller font
        pdf.set_fill_color(220, 220, 220)     # Light background (almost white)
    else:
        pdf.set_font('Dejavu_Sans', 'B', 12)  # Bold font for main sections
        pdf.set_fill_color(200, 200, 200)     # Light gray

    # Header cell
    pdf.cell(0, 10, section_name, 0, new_x=XPos.LMARGIN, new_y=YPos.NEXT,
             align='L', fill=1)
    pdf.ln(2)

    # Clean summary lines from content
    lines = section_content.splitlines()
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if line.startswith("== Summary"):
            continue
        if any(keyword in line for keyword in ["checks PASS", "checks FAIL", "checks WARN", "checks INFO"]):
            continue

        cleaned_lines.append(line)

    cleaned_content = '\n'.join(cleaned_lines)

    # Parse and render tests
    tests = parse_tests(cleaned_content)
    for test in tests:
        render_test(pdf, test)

    pdf.ln(5)


def parse_tests(section_content):
    """Parse individual test results from a section"""
    tests = []
    test_pattern = r'(\d+\.\d+.*?)(?=\d+\.\d+|\Z)'
    
    for match in re.finditer(test_pattern, section_content, re.DOTALL):
        test_text = match.group(1).strip()
        if test_text:
            # Extract test details
            test_id_match = re.search(r'(\d+\.\d+\.\d+)', test_text)
            test_id = test_id_match.group(1) if test_id_match else "Unknown"
            
            title_match = re.search(r'\d+\.\d+\.\d+\s+(.*?)(?=\[)', test_text)
            title = title_match.group(1).strip() if title_match else "Unknown Test"
            
            status_match = re.search(r'\[(PASS|FAIL|WARN|INFO)\]', test_text)
            status = status_match.group(1) if status_match else "UNKNOWN"

            details = test_text

            tests.append({
                'id': test_id,
                'title': title,
                'status': status,
                'details': details
            })

    return tests

def render_test(pdf, test):
    """Render a test with status color-coded, no title, and cleaned details (no ID or status inside)"""
    from fpdf import XPos, YPos
    import re

    # Print test ID (black)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Dejavu_Sans', 'B', 10)
    pdf.cell(0, 8, f"Test ID: {test['id']}", 0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Print status in color
    if test['status'] == 'PASS':
        pdf.set_text_color(0, 128, 0)  # Green
    elif test['status'] == 'FAIL':
        pdf.set_text_color(255, 0, 0)  # Red
    elif test['status'] == 'WARN':
        pdf.set_text_color(255, 165, 0)  # Orange
    else:
        pdf.set_text_color(0, 0, 0)  # Black

    pdf.set_font('Dejavu_Sans', 'B', 10)
    pdf.cell(0, 8, f"Status: {test['status']}", 0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Clean details: remove status and test ID
    clean_details = test['details']
    clean_details = re.sub(r'\[(PASS|FAIL|WARN|INFO)\]', '', clean_details)  # Remove status
    clean_details = re.sub(rf'^{re.escape(test["id"])}\s*', '', clean_details)  # Remove test ID from start
    clean_details = clean_details.strip()

    # Reset text color and add details
    pdf.set_text_color(0, 0, 0)
    pdf.set_font('Dejavu_Sans', '', 9)
    pdf.multi_cell(0, 5, clean_details)
    pdf.ln(3)

def cleanup_kube_bench_job(job_name="kube-bench", namespace="default"):
    batch_v1 = client.BatchV1Api()
    delete_opts = client.V1DeleteOptions(propagation_policy='Foreground')

    batch_v1.delete_namespaced_job(name=job_name, namespace=namespace, body=delete_opts)
    print("🧹 Job cleaned up.")

try:
    run_kube_bench_job()
    logs = get_kube_bench_logs()
    generate_kube_bench_pdf(logs, filename="kube_bench_report_dejavu_sans.pdf")
    # print("📝 Kube-bench logs:", logs)
except Exception as e:
    print(f"❌ An error occurred: {e}")
finally:
    cleanup_kube_bench_job()