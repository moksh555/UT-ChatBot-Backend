import requests
from bs4 import BeautifulSoup
import PyPDF2
import io
import json
import os
from datetime import datetime
from urllib.parse import urljoin, urlparse
import time
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

class TextCleaner:
    """Clean text in real-time as we scrape"""
    
    def __init__(self):
        self.boilerplate_patterns = [
            r'skip to main content', r'skip navigation', r'toggle navigation',
            r'search this site', r'©\s*\d{4}.*all rights reserved',
            r'copyright.*\d{4}', r'privacy policy\s*\|?\s*terms',
            r'follow us on', r'share this page', r'print this page',
            r'back to top', r'cookie policy', r'powered by.*', r'site by.*',
        ]

    def clean(self, text: str) -> str:
        if not text:
            return ""
        
        # Unicode normalization
        text = unicodedata.normalize('NFC', text)
        
        # Fix common unicode issues
        replacements = {
            '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
            '\u2013': '-', '\u2014': '-', '\u2026': '...', '\xa0': ' ', '\u200b': '',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Remove boilerplate
        for pattern in self.boilerplate_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # Clean whitespace
        text = re.sub(r' +', ' ', text)
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        
        # Remove very short lines (navigation items)
        lines = text.split('\n')
        lines = [line.strip() for line in lines if len(line.strip()) >= 20 or line.strip() == '']
        text = '\n'.join(lines)
        
        # Fix PDF artifacts
        text = re.sub(r'^\d+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'(Page \d+ of \d+)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'[•·∙●○■□▪▫]', '* ', text)
        
        # Normalize URLs and emails
        text = re.sub(r'https?://[^\s]+', '[URL]', text)
        text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
        
        return text.strip()
    
    def chunk_text(self, text: str, chunk_size=512, overlap=50) -> list:
        """Split text into overlapping chunks"""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), chunk_size - overlap):
            chunk = ' '.join(words[i:i + chunk_size])
            if len(chunk.split()) >= 20:  # At least 20 words
                chunks.append(chunk)
        
        return chunks


class UniversityScraper:
    def __init__(self, base_url, university_name, output_dir='scraped_data'):
        self.base_url = base_url
        self.university_name = university_name
        self.output_dir = output_dir
        self.visited_urls = set()
        self.documents = []
        self.chunks = []  # Store cleaned chunks ready for embeddings
        self.lock = threading.Lock()
        self.cleaner = TextCleaner()  # Text cleaner
        
        # Create output directory structure
        os.makedirs(f"{output_dir}/pdfs/{university_name}", exist_ok=True)
        os.makedirs(f"{output_dir}/processed", exist_ok=True)
        os.makedirs(f"{output_dir}/embeddings_ready", exist_ok=True)
        
        self.headers = {
            'User-Agent': 'UT-Chatbot-Scraper (Educational Use - Contact: ""@gmail.com)'
        }
    
    def scrape_page(self, url):
        if url in self.visited_urls:
            return None
        
        with self.lock:
            if url in self.visited_urls:
                return None
            self.visited_urls.add(url)
        
        print(f"[{self.university_name}] Scraping: {url}")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            
            # Extract metadata
            title = soup.title.string if soup.title else 'No Title'
            
            # Extract main content
            main_content = soup.find('main') or soup.find('article') or soup.find('body')
            text_content = main_content.get_text(separator='\n', strip=True) if main_content else ''
            
            # CLEAN TEXT IN REAL-TIME
            text_cleaned = self.cleaner.clean(text_content)
            
            # Skip if too short after cleaning
            if len(text_cleaned.split()) < 50:
                print(f"[{self.university_name}]    ⚠️  Skipped (too short after cleaning)")
                return None
            
            # Store raw document
            doc = {
                'url': url,
                'university': self.university_name,
                'title': title,
                'content': text_cleaned,  # Already cleaned!
                'type': 'webpage',
                'scraped_at': datetime.now().isoformat(),
                'word_count': len(text_cleaned.split())
            }
            
            with self.lock:
                self.documents.append(doc)
            
            # CREATE CHUNKS IN REAL-TIME
            chunks = self.cleaner.chunk_text(text_cleaned)
            for idx, chunk_text in enumerate(chunks):
                chunk_doc = {
                    'chunk_id': f"{self.university_name}_{len(self.chunks)}",
                    'text': chunk_text,
                    'metadata': {
                        'university': self.university_name,
                        'source_url': url,
                        'title': title,
                        'type': 'webpage',
                        'chunk_index': idx,
                        'word_count': len(chunk_text.split()),
                        'scraped_at': datetime.now().isoformat()
                    }
                }
                with self.lock:
                    self.chunks.append(chunk_doc)
            
            # Find all links on the page
            links = []
            for link in soup.find_all('a', href=True):
                absolute_url = urljoin(url, link['href'])
                if self.is_valid_url(absolute_url):
                    links.append(absolute_url)
            
            # Find PDF links
            pdf_links = [link for link in links if link.lower().endswith('.pdf')]
            for pdf_url in pdf_links:
                self.download_and_extract_pdf(pdf_url)
            
            time.sleep(1)
            return links
            
        except Exception as e:
            print(f"[{self.university_name}] Error scraping {url}: {e}")
            return None
    
    def download_and_extract_pdf(self, pdf_url):
        """Download and extract text from PDF with real-time cleaning"""
        with self.lock:
            if pdf_url in self.visited_urls:
                return
            self.visited_urls.add(pdf_url)
        
        print(f"[{self.university_name}] Downloading PDF: {pdf_url}")
        
        try:
            # Check file size
            head_response = requests.head(pdf_url, headers=self.headers, timeout=10, allow_redirects=True)
            
            if head_response.status_code == 404:
                print(f"[{self.university_name}] ⚠️  PDF not found (404)")
                return
            
            file_size = int(head_response.headers.get('content-length', 0))
            file_size_mb = file_size / (1024 * 1024)
            
            # Skip very large files
            if file_size > 5 * 1024 * 1024:
                print(f"[{self.university_name}] ⚠️  Skipping large PDF ({file_size_mb:.1f}MB)")
                return
            
            print(f"[{self.university_name}]    Size: {file_size_mb:.1f}MB - Downloading...")
            
            # Download
            response = requests.get(pdf_url, headers=self.headers, timeout=60, stream=True)
            response.raise_for_status()
            
            pdf_content = b''
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    pdf_content += chunk
            
            # Save PDF
            pdf_filename = os.path.basename(urlparse(pdf_url).path)
            if not pdf_filename:
                pdf_filename = f"document_{len(self.documents)}.pdf"
            
            pdf_path = f"{self.output_dir}/pdfs/{self.university_name}/{pdf_filename}"
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)
            
            print(f"[{self.university_name}]    Extracting text...")
            
            # Extract text
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
            num_pages = len(pdf_reader.pages)
            max_pages = min(num_pages, 200)
            
            text_content = ''
            for page_num in range(max_pages):
                try:
                    page = pdf_reader.pages[page_num]
                    text_content += page.extract_text() + '\n\n'
                except:
                    continue
            
            # CLEAN TEXT IN REAL-TIME
            text_cleaned = self.cleaner.clean(text_content)
            
            # Skip if too short
            if len(text_cleaned.split()) < 50:
                print(f"[{self.university_name}] Skipped (too short after cleaning)")
                return
            
            # Store document
            doc = {
                'url': pdf_url,
                'university': self.university_name,
                'title': pdf_filename,
                'content': text_cleaned,
                'type': 'pdf',
                'scraped_at': datetime.now().isoformat(),
                'word_count': len(text_cleaned.split()),
                'page_count': num_pages,
                'file_size_mb': round(file_size_mb, 2)
            }
            
            with self.lock:
                self.documents.append(doc)
            
            # CREATE CHUNKS IN REAL-TIME
            chunks = self.cleaner.chunk_text(text_cleaned)
            for idx, chunk_text in enumerate(chunks):
                chunk_doc = {
                    'chunk_id': f"{self.university_name}_{len(self.chunks)}",
                    'text': chunk_text,
                    'metadata': {
                        'university': self.university_name,
                        'source_url': pdf_url,
                        'title': pdf_filename,
                        'type': 'pdf',
                        'chunk_index': idx,
                        'word_count': len(chunk_text.split()),
                        'scraped_at': datetime.now().isoformat()
                    }
                }
                with self.lock:
                    self.chunks.append(chunk_doc)
            
            print(f"[{self.university_name}]    Completed: {len(text_cleaned.split())} words, {len(chunks)} chunks")
            time.sleep(1)
            
        except requests.exceptions.Timeout:
            print(f"[{self.university_name}] Timeout")
        except Exception as e:
            print(f"[{self.university_name}] Error: {str(e)[:50]}")
    
    def is_valid_url(self, url):
        parsed = urlparse(url)
        base_parsed = urlparse(self.base_url)
        return (parsed.netloc == base_parsed.netloc and 
                not url.endswith(('.jpg', '.png', '.gif', '.zip', '.doc', '.docx', '.mp4', '.mp3')))
    
    def crawl_site(self, start_urls, max_pages=100):
        """Crawl pages"""
        self.max_pages = max_pages
        to_visit = list(start_urls)
        pages_scraped = 0
        
        while to_visit and pages_scraped < max_pages:
            url = to_visit.pop(0)
            
            if url not in self.visited_urls:
                links = self.scrape_page(url)
                pages_scraped += 1
                
                if links:
                    new_links = [l for l in links if l not in self.visited_urls]
                    to_visit.extend(new_links[:50])
                
                if pages_scraped % 10 == 0:
                    print(f"[{self.university_name}] Progress: {pages_scraped}/{max_pages} pages | {len(self.documents)} docs | {len(self.chunks)} chunks")
        
        print(f"[{self.university_name}] Complete! {len(self.documents)} docs | {len(self.chunks)} chunks")
    
    def save_documents(self):
        """Save both raw documents and embedding-ready chunks"""
        
        # Save raw documents
        raw_file = f"{self.output_dir}/processed/{self.university_name}_documents.json"
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(self.documents, f, indent=2, ensure_ascii=False)
        
        # Save embedding-ready chunks
        chunks_file = f"{self.output_dir}/embeddings_ready/{self.university_name}_chunks.json"
        with open(chunks_file, 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, indent=2, ensure_ascii=False)
        
        print(f"[{self.university_name}] Saved:")
        print(f"[{self.university_name}] Raw: {raw_file}")
        print(f"[{self.university_name}] Chunks: {chunks_file}")
        
        # Stats
        stats = {
            'university': self.university_name,
            'total_documents': len(self.documents),
            'total_chunks': len(self.chunks),
            'webpages': sum(1 for d in self.documents if d['type'] == 'webpage'),
            'pdfs': sum(1 for d in self.documents if d['type'] == 'pdf'),
            'total_words': sum(d['word_count'] for d in self.documents),
            'avg_chunk_size': sum(c['metadata']['word_count'] for c in self.chunks) / len(self.chunks) if self.chunks else 0,
            'scraped_at': datetime.now().isoformat()
        }
        
        stats_file = f"{self.output_dir}/processed/{self.university_name}_stats.json"
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
        
        return raw_file, chunks_file


# UT System Schools Configuration
UT_SYSTEM_SCHOOLS = [
#     {
#         'name': 'UT_Austin',
#         'base_url': 'https://www.utexas.edu',
#         'start_urls': [
#     # Existing + previous set
#     'https://www.utexas.edu/academics',
#     'https://www.utexas.edu/academics/undergraduate-programs',
#     'https://www.utexas.edu/academics/graduate-programs',
#     'https://admissions.utexas.edu/',
#     'https://catalog.utexas.edu/',
#     'https://registrar.utexas.edu/',
#     'https://finaid.utexas.edu/',
#     'https://housing.utexas.edu/',
#     'https://www.utexas.edu/academics/schools-and-colleges',
#     'https://www.utexas.edu/research',
#     'https://students.utexas.edu/',
#     'https://ugs.utexas.edu/',
#     'https://registrar.utexas.edu/schedules',
#     'https://onestop.utexas.edu/',
#     'https://careerengagement.utexas.edu/',
#     'https://lib.utexas.edu/',
#     'https://orientation.utexas.edu/',
#     'https://www.mccombs.utexas.edu/',
#     'https://cockrell.utexas.edu/',
#     'https://cns.utexas.edu/',
#     'https://gradschool.utexas.edu/',
#     'https://global.utexas.edu/',
#     'https://policies.utexas.edu/',
#     'https://resources.utexas.edu/',

#     # Additional deep, rich UT Austin subdomains
#     'https://registrar.utexas.edu/calendars',
#     'https://healthyi.utexas.edu/',                     # Mental health & wellbeing portal
#     'https://cllc.utexas.edu/',                         # Language centers & culture programs
#     'https://finearts.utexas.edu/',                     # College of Fine Arts
#     'https://moody.utexas.edu/',                        # Moody College of Communication
#     'https://edb.utexas.edu/',                          # College of Education
#     'https://pharmacy.utexas.edu/',                     # College of Pharmacy
#     'https://law.utexas.edu/',                          # UT Law School
#     'https://medicalschool.utexas.edu/',                # Dell Medical School
#     'https://nursing.utexas.edu/',                      # School of Nursing

#     # Student life, orgs, services
#     'https://deanofstudents.utexas.edu/',
#     'https://recsports.utexas.edu/',
#     'https://livingthelonghornlife.com/',               # Student engagement & events
#     'https://hornslink.com/',                           # Student organizations directory
#     'https://utdirect.utexas.edu/apps/registrar/course_schedule/',

#     # Research centers & institutes
#     'https://www.tacc.utexas.edu/',                     # Texas Advanced Computing Center
#     'https://www.ic2.utexas.edu/',                      # IC² Institute (innovation)
#     'https://energy.utexas.edu/',                       # Energy Institute
#     'https://bridgingbarriers.utexas.edu/',             # Grand Challenge research initiatives

#     # Administrative & governance
#     'https://provost.utexas.edu/',
#     'https://president.utexas.edu/',
#     'https://facultycouncil.utexas.edu/',
#     'https://compliance.utexas.edu/',
#     'https://security.utexas.edu/',

#     # Support services
#     'https://its.utexas.edu/',                          # Tech support
#     'https://utlearn.utexas.edu/',                      # Employee/student learning hub
#     'https://parking.utexas.edu/',                      # Parking & transportation
#     'https://environmentalhealthsafety.utexas.edu/',    # EHS

#     # Libraries, collections, museums
#     'https://hrc.utexas.edu/',                          # Harry Ransom Center
#     'https://blantonmuseum.org/',                       # Blanton Museum of Art
#     'https://texasexes.org/',                           # Alumni Association
#     # Core academic PDFs
#     'https://catalog.utexas.edu/media/',                     # Course catalogs (PDFs)
#     'https://registrar.utexas.edu/schedules',                # PDFs for schedules, add/drop, finals
#     'https://registrar.utexas.edu/calendars',                # Academic calendars in PDF
#     'https://utexas.app.box.com/v/ucc-reports',              # Core Curriculum Reports (PDF)
#     'https://provost.utexas.edu/policies-and-procedures',    # Policy PDFs

#     # Financial aid / housing / tuition PDFs
#     'https://financialaid.utexas.edu/forms',                 # All forms are PDF
#     'https://housing.utexas.edu/resources/',                 # Contracts, guides (PDF)
#     'https://onestop.utexas.edu/tuition/',                   # Tuition/fee sheets (PDF)

#     # Student services & compliance PDFs
#     'https://secure.dcsg.utexas.edu/dcsg/forms',             # Student forms (PDF)
#     'https://compliance.utexas.edu/policies/',               # Compliance docs (PDF)
#     'https://environmentalhealthsafety.utexas.edu/',         # Safety manuals (PDF)

#     # Research centers with PDF reports
#     'https://energy.utexas.edu/research',                    # Research publications (many PDFs)
#     'https://www.tacc.utexas.edu/documents',                 # TACC documentation (PDF)
#     'https://ic2.utexas.edu/reports/',                       # PDF research reports
#     'https://bridgingbarriers.utexas.edu/reports/',          # Grand Challenge reports (PDF)

#     # Graduate school PDFs
#     'https://gradschool.utexas.edu/academics/policies',      # Graduate policies (PDF)
#     'https://gradschool.utexas.edu/admissions/resources',    # Admissions PDFs

#     # HR / governance PDFs
#     'https://policies.utexas.edu/policies',                  # All UT System + UT Austin policies
#     'https://hr.utexas.edu/forms',                           # HR forms (PDF)
#     'https://facultycouncil.utexas.edu/legislation',         # Legislation PDFs

#     # Campus safety / handbooks
#     'https://police.utexas.edu/reports',                     # Crime & safety reports (PDF)
#     'https://utexas.box.com/v/student-handbooks',            # Handbooks (PDF)

#     # Library special collections PDFs
#     'https://hrc.utexas.edu/research',                       # Guides & finding aids (PDF)
#     'https://repositories.lib.utexas.edu/',   
# ]
# ,
#         'max_pages': 2000
#     },
#     {
#         'name': 'UT_Dallas',
#         'base_url': 'https://www.utdallas.edu',
#         'start_urls': [
#             'https://www.utdallas.edu/academics/',
#             'https://www.utdallas.edu/enroll/',
#             'https://catalog.utdallas.edu/',
#         ],
#         'max_pages': 2000
#     },
#     {
#         'name': 'UT_Arlington',
#         'base_url': 'https://www.uta.edu',
#         'start_urls': [
#             'https://www.uta.edu/academics',
#             'https://www.uta.edu/admissions',
#             'https://catalog.uta.edu/',
#             # Academic policies & regulations
#             'https://resources.uta.edu/provost/policies-procedures/index.php',       # General UTA policies & procedures :contentReference[oaicite:1]{index=1}
#             'https://www.uta.edu/administration/registrar/students/policies-procedures',  # Registrar’s policies & procedures :contentReference[oaicite:2]{index=2}
#             'https://cdn.prod.web.uta.edu/-/media/project/website/cappa/documents/admissions-and-advising/forms/academic-integrity.pdf',  # Example PDF: Academic Integrity policy :contentReference[oaicite:3]{index=3}

#             # Legal / Administrative forms & documents
#             'https://resources.uta.edu/legal-affairs/forms/',                       # Legal-affairs forms (PDFs) :contentReference[oaicite:4]{index=4}
            
#             # Research & compliance documents
#             'https://resources.uta.edu/research/policies-and-procedures/index.php',  # Research-related policies (often PDF) :contentReference[oaicite:5]{index=5}
#             'https://resources.uta.edu/research/regulatory-services/human-subjects/irb-policies-and-procedures%20.php',  # IRB / human-subjects docs :contentReference[oaicite:6]{index=6}

#             # Registrar / Academic calendars & schedules (often downloadable / printable format)
#             'https://www.uta.edu/administration/registrar/calendars',                # Academic calendars, class schedules, etc. :contentReference[oaicite:7]{index=7}
#             'https://www.uta.edu/administration/registrar/students/registration/schedules',  # Schedule-of-classes & registration schedule pages :contentReference[oaicite:8]{index=8}
#         ],
#         'max_pages': 2000
#     },
#     {
#         'name': 'UT_San_Antonio',
#         'base_url': 'https://www.utsa.edu',
#         'start_urls': [
#             'https://www.utsa.edu/academics/',
#             'https://www.utsa.edu/admissions/',
#             'https://catalog.utsa.edu/',
#         ],
#         'max_pages': 2000
#     },
    # {
    #     'name': 'UT_El_Paso',
    #     'base_url': 'https://www.utep.edu',
    #     'start_urls': [
    # # Registrar & academic calendars / schedules
    #         'https://www.utep.edu/registrar/academic-calendars/',
    #         'https://www.utep.edu/registrar/students/student-forms.html',
    #         'https://www.utep.edu/registrar/scheduling/',
    #         'https://www.utep.edu/registrar/',

    #         # Forms / Enrollment & Verification PDFs
    #         'https://www.utep.edu/registrar/students/Forms/Other/ENROLLMENT%20VERIFICATION%20FORM.pdf',
    #         'https://www.utep.edu/registrar/students/student-forms.html',

    #         # Student-services & policies / resources
    #         'https://www.utep.edu/resources/students.html',

    #         # Business / payment / student-business-services deadlines & documents
    #         'https://www.utep.edu/vpba/student-business-services/home/important-dates.html',
    #         'https://www.utep.edu/vpba/forms-library/',
            
    #         # Faculty / academic-policy calendars (sometimes pdf or print-ready)
    #         'https://www.utep.edu/provost/policies/faculty-affairs-calendar.html',
    #     ],
    #     'max_pages': 1000
    # },
    # {
    #     'name': 'UT_Rio_Grande_Valley',
    #     'base_url': 'https://www.utrgv.edu',
    #     'start_urls': [
    #         'https://www.utrgv.edu/academics/index.htm',
    #         'https://www.utrgv.edu/admissions/index.htm',
    #     ],
    #     'max_pages': 2000
    # },
    # {
    #     'name': 'UT_Permian_Basin',
    #     'base_url': 'https://www.utpb.edu',
    #     'start_urls': [
    #         'https://www.utpb.edu/academics',
    #         'https://www.utpb.edu/admissions',
    #     ],
    #     'max_pages': 2000
    # },
    # {
    #     'name': 'UT_Tyler',
    #     'base_url': 'https://www.uttyler.edu',
    #     'start_urls': [
    #         'https://www.uttyler.edu/academics/',
    #         'https://www.uttyler.edu/admissions/',
    #     ],
    #     'max_pages': 1000
    # },
    # {
    #     'name': 'UT_Health_San_Antonio',
    #     'base_url': 'https://www.uthscsa.edu',
    #     'start_urls': [
    #         'https://www.uthscsa.edu/academics',
    #         'https://www.uthscsa.edu/admissions',
    #     ],
    #     'max_pages': 2000
    # },
    # {
    #     'name': 'UT_Health_Houston',
    #     'base_url': 'https://www.uth.edu',
    #     'start_urls': [
    #         'https://www.uth.edu/academics/',
    #         'https://www.uth.edu/admissions/',
    #     ],
    #     'max_pages': 700
    # },
    # {
    #     'name': 'UT_MD_Anderson',
    #     'base_url': 'https://www.mdanderson.org',
    #     'start_urls': [
    #         'https://www.mdanderson.org/education-training.html',
    #     ],
    #     'max_pages': 2000
    # },
#     {
#     'name': 'UT_Medical_Branch_Galveston',
#     'base_url': 'https://www.utmb.edu',
#     'start_urls': [
#         'https://www.utmb.edu/som',
#         'https://www.utmb.edu/admissions',

#         # Academics / Schools
#         'https://www.utmb.edu/som/medical-education',
#         'https://www.utmb.edu/sph',                           # School of Public Health
#         'https://www.utmb.edu/gsbs',                          # Graduate School of Biomedical Sciences

#         # Research
#         'https://www.utmb.edu/research',
#         'https://www.utmb.edu/cehs',                          # Environmental Health Sciences
#         'https://www.utmb.edu/ctsa',                          # Clinical and Translational Science

#         # Hospitals / Clinics
#         'https://www.utmbhealth.com/locations',
#         'https://www.utmbhealth.com/services',
#         'https://www.utmbhealth.com/patient-care',

#         # Students
#         'https://www.utmb.edu/enrollment-services',
#         'https://www.utmb.edu/studentlife',
#         'https://www.utmb.edu/studentservices',
#         'https://www.utmb.edu/finance/student-financial-services',

#         # Registrars / Catalog / Policies
#         'https://www.utmb.edu/enrollment-services/registrar',
#         'https://www.utmb.edu/policies',
#         'https://www.utmb.edu/oaam',                          # Office of Academic Affairs & Medicine

#         # Residency / GME
#         'https://www.utmb.edu/gme',
#         'https://www.utmb.edu/gme/programs',
#         'https://www.utmb.edu/surgery/education/residency',

#         # Libraries / Learning Resources
#         'https://www.utmb.edu/ar',                            # Academic Resources
#         'https://www.utmb.edu/library',                       # Moody Medical Library

#         # Public-facing resources
#         'https://www.utmb.edu/news',
#         'https://www.utmb.edu/communications',
#         'https://www.utmb.edu/hr',                            # HR, jobs, hiring, policies
#     ],
#     'max_pages': 1000
# },
    # {
    #     'name': 'UT_Southwestern',
    #     'base_url': 'https://www.utsouthwestern.edu',
    #     'start_urls': [
    #         'https://www.utsouthwestern.edu/education/',
    #     ],
    #     'max_pages': 2000
    # },
    # {
    #     'name': 'UT_Health_Science_Center_Tyler',
    #     'base_url': 'https://www.uthct.edu',
    #     'start_urls': [
    #         'https://www.uthct.edu/academics/',
    #     ],
    #     'max_pages': 2000
    # }
]


def scrape_single_school(school_config):
    """Scrape one school with real-time cleaning"""
    try:
        print(f"\n{'='*80}")
        print(f"STARTING: {school_config['name']}")
        print(f"{'='*80}\n")
        
        scraper = UniversityScraper(
            base_url=school_config['base_url'],
            university_name=school_config['name']
        )
        
        scraper.crawl_site(school_config['start_urls'], max_pages=school_config['max_pages'])
        raw_file, chunks_file = scraper.save_documents()
        
        result = {
            'name': school_config['name'],
            'documents': len(scraper.documents),
            'chunks': len(scraper.chunks),
            'status': 'success'
        }
        
        print(f"\nCOMPLETED: {school_config['name']}")
        return result, scraper.documents, scraper.chunks
        
    except Exception as e:
        print(f"\nFAILED: {school_config['name']} - {e}")
        return {
            'name': school_config['name'],
            'documents': 0,
            'chunks': 0,
            'status': 'failed',
            'error': str(e)
        }, [], []


def scrape_all_ut_schools_parallel(max_workers=4):
    """Scrape all schools in parallel with real-time cleaning"""
    
    print("="*80)
    print("UT SYSTEM PARALLEL SCRAPER WITH REAL-TIME CLEANING")
    print(f"Parallel Workers: {max_workers}")
    print("="*80)
    print(f"\nStarting scrape of {len(UT_SYSTEM_SCHOOLS)} UT institutions\n")
    
    start_time = time.time()
    all_documents = []
    all_chunks = []
    results_summary = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_school = {
            executor.submit(scrape_single_school, school): school
            for school in UT_SYSTEM_SCHOOLS
        }
        
        for future in as_completed(future_to_school):
            try:
                result, documents, chunks = future.result()
                results_summary.append(result)
                all_documents.extend(documents)
                all_chunks.extend(chunks)
                
                completed = len(results_summary)
                print(f"\nPROGRESS: {completed}/{len(UT_SYSTEM_SCHOOLS)} schools")
                print(f"   Total chunks (ready for embeddings): {len(all_chunks):,}")
                
            except Exception as e:
                print(f"\nException: {e}")
    
    # Save combined files
    print("\n" + "="*80)
    print("SAVING COMBINED DATASETS")
    print("="*80)
    
    # Combined raw documents
    combined_raw = 'scraped_data/processed/all_ut_schools_combined.json'
    with open(combined_raw, 'w', encoding='utf-8') as f:
        json.dump(all_documents, f, indent=2, ensure_ascii=False)
    print(f"Raw documents: {combined_raw}")
    
    # Combined embedding-ready chunks
    combined_chunks = 'scraped_data/embeddings_ready/all_ut_schools_chunks.json'
    with open(combined_chunks, 'w', encoding='utf-8') as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)
    print(f"Embedding chunks: {combined_chunks}")
    
    # Summary
    total_time = time.time() - start_time
    summary = {
        'scraped_at': datetime.now().isoformat(),
        'total_schools': len(UT_SYSTEM_SCHOOLS),
        'successful': sum(1 for r in results_summary if r['status'] == 'success'),
        'total_documents': len(all_documents),
        'total_chunks': len(all_chunks),
        'total_words': sum(doc.get('word_count', 0) for doc in all_documents),
        'avg_chunk_size': sum(c['metadata']['word_count'] for c in all_chunks) / len(all_chunks) if all_chunks else 0,
        'time_minutes': round(total_time / 60, 2),
        'schools': results_summary
    }
    
    summary_file = 'scraped_data/processed/scraping_summary.json'
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n{'='*80}")
    print("SCRAPING COMPLETE!")
    print(f"{'='*80}")
    print(f"Schools scraped: {summary['successful']}/{summary['total_schools']}")
    print(f"Total documents: {summary['total_documents']:,}")
    print(f"Total chunks (ready for embeddings): {summary['total_chunks']:,}")
    print(f"Avg chunk size: {summary['avg_chunk_size']:.0f} words")
    print(f"Time: {total_time/60:.1f} minutes")
    print(f"\nYour data is in:")
    print(f"   scraped_data/embeddings_ready/all_ut_schools_chunks.json")
    print(f"\nNext: Generate embeddings from the chunks file!")
    
    return summary


if __name__ == "__main__":
    summary = scrape_all_ut_schools_parallel(max_workers=4)