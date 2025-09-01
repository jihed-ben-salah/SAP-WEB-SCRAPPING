import asyncio
import json
import os
import re
import pandas as pd
import base64
import aiohttp
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright, TimeoutError

# remove scheme constant to avoid duplicated literal
URL_SCHEME = "https://"

def load_existing_progress(base_filename):
    """Load existing scraped data to find the last scraped URL"""
    # Deprecated: No longer used. Only checkpoint is used for resume.
    return set(), 0

def save_progress_checkpoint(base_filename, current_page, current_url):
    """Save a checkpoint file with current progress"""
    scrapped_data_dir = "scrapped_data"
    os.makedirs(scrapped_data_dir, exist_ok=True)
    
    checkpoint = {
        'last_page': current_page,
        'last_url': current_url,
        'timestamp': pd.Timestamp.now().isoformat()
    }
    
    checkpoint_file = os.path.join(scrapped_data_dir, f"{base_filename}_checkpoint.json")
    try:
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error saving checkpoint: {e}")

def load_progress_checkpoint(base_filename):
    """Load the last checkpoint to resume scraping"""
    scrapped_data_dir = "scrapped_data"
    checkpoint_file = os.path.join(scrapped_data_dir, f"{base_filename}_checkpoint.json")
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
                return checkpoint.get('last_page', 0), checkpoint.get('last_url', '')
        except Exception as e:
            print(f"⚠️ Error loading checkpoint: {e}")
    
    return 0, ''

def reset_progress(base_filename):
    """Reset all progress files to start fresh"""
    scrapped_data_dir = "scrapped_data"
    files_to_remove = [
        os.path.join(scrapped_data_dir, f"{base_filename}_accepted.json"),
        os.path.join(scrapped_data_dir, f"{base_filename}_no_accepted.json"),
        os.path.join(scrapped_data_dir, f"{base_filename}_checkpoint.json"),
        os.path.join(scrapped_data_dir, f"{base_filename}.xlsx")
    ]
    
    removed_count = 0
    for file_path in files_to_remove:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"🗑️ Removed: {file_path}")
                removed_count += 1
            except Exception as e:
                print(f"⚠️ Error removing {file_path}: {e}")
    
    if removed_count > 0:
        print(f"✅ Reset complete! Removed {removed_count} progress files.")
    else:
        print("ℹ️ No progress files found to remove.")

def generate_filename_from_url(url):
    """Generate a safe filename from URL"""
    import re
    from urllib.parse import urlparse
    
    # Parse the URL
    parsed = urlparse(url)
    path = parsed.path
    
    # Extract meaningful parts from the path
    # For SAP Community URLs like /t5/supply-chain-management-q-a/qa-p/scm-questions
    parts = [part for part in path.split('/') if part and part not in ['t5', 'qa-p', 'ct-p']]
    
    if parts:
        # Take the main section name
        section_name = parts[0] if parts else 'sap-community'
        # Clean up the name for Windows filename
        clean_name = re.sub(r'[<>:"/\\|?*]', '_', section_name)
        clean_name = re.sub(r'[-\s]+', '_', clean_name)
        return f"sap_community_{clean_name}"
    else:
        return "sap_community_data"

async def extract_images_from_element(page, element, base_url, images_dir="images"):
    """Extract all images from an element and save them locally"""
    images = []
    
    try:
        # Create images directory if it doesn't exist
        os.makedirs(images_dir, exist_ok=True)
        
        # Find all image elements
        img_elements = await element.query_selector_all("img")
        
        for i, img in enumerate(img_elements):
            try:
                # Get image source
                src = await img.get_attribute("src")
                alt = await img.get_attribute("alt") or f"image_{i}"
                
                if not src:
                    continue
                
                # Handle relative URLs
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urljoin(base_url, src)
                elif not src.startswith('http'):
                    src = urljoin(base_url, src)
                
                # Generate safe filename
                parsed_url = urlparse(src)
                file_ext = os.path.splitext(parsed_url.path)[1] or '.jpg'
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', alt)[:50] + f"_{i}{file_ext}"
                local_path = os.path.join(images_dir, safe_filename)
                
                # Download image
                async with aiohttp.ClientSession() as session:
                    async with session.get(src) as response:
                        if response.status == 200:
                            content = await response.read()
                            with open(local_path, 'wb') as f:
                                f.write(content)
                            
                            images.append({
                                "original_url": src,
                                "local_path": local_path,
                                "alt_text": alt,
                                "filename": safe_filename
                            })
                        
            except Exception as e:
                print(f"⚠️ Failed to download image {i}: {e}")
                
    except Exception as e:
        print(f"⚠️ Error extracting images: {e}")
    
    return images

async def extract_all_responses(page):
    """Extract all responses/answers from a question page"""
    responses = []
    
    try:
        # Find all message/answer elements
        answer_elements = await page.query_selector_all(".MessageView.lia-message-view-qanda-answer")
        
        for i, answer_elem in enumerate(answer_elements):
            try:
                # Extract response text
                response_text = ""
                body_selectors = ['.lia-message-body', '[id^="bodyDisplay"]']
                
                for sel in body_selectors:
                    if await answer_elem.query_selector(sel):
                        body_el = await answer_elem.query_selector(sel)
                        response_text = await body_el.inner_text()
                        break
                
                if not response_text:
                    response_text = await answer_elem.inner_text()
                
                # Check if this is an accepted answer
                is_accepted = False
                classes = await answer_elem.get_attribute("class") or ""
                if "lia-accepted-solution" in classes or "lia-list-row-thread-solved" in classes:
                    is_accepted = True
                
                # Extract author info if available
                author = ""
                author_elem = await answer_elem.query_selector(".lia-user-name-link, .lia-user-name")
                if author_elem:
                    author = await author_elem.inner_text()
                
                # Extract date if available
                date = ""
                date_elem = await answer_elem.query_selector(".lia-message-posted-on, .DateTime")
                if date_elem:
                    date = await date_elem.inner_text()
                
                # Extract images from this response
                base_url = page.url
                images = await extract_images_from_element(page, answer_elem, base_url)
                
                response_data = {
                    "response_number": i + 1,
                    "text": response_text.strip(),
                    "is_accepted": is_accepted,
                    "author": author.strip(),
                    "date": date.strip(),
                    "images": images
                }
                
                responses.append(response_data)
                
            except Exception as e:
                print(f"⚠️ Error extracting response {i}: {e}")
                
    except Exception as e:
        print(f"⚠️ Error extracting responses: {e}")
    
    return responses

async def scrape_sap_community(topic_url, max_pages=1, debug=False, save_diagnostics_dir="diagnostics", max_questions=None, resume=True):
    """
    Scrape questions + accepted answers from SAP Community.
    Only keeps entries with an accepted solution.
    
    Args:
        topic_url: URL to scrape
        max_pages: Maximum pages to scrape
        debug: Enable debug mode
        save_diagnostics_dir: Directory for debug files
        max_questions: Maximum questions to scrape (None for unlimited)
        resume: Whether to resume from last scraped position
    """

    accepted_results = []
    no_accepted_results = []

    # Generate base filename from URL
    base_filename = generate_filename_from_url(topic_url)
    
    # Only use checkpoint for resume
    start_page = 1
    if resume:
        print("🔄 Checking for existing progress...")
        last_page_from_checkpoint, last_url = load_progress_checkpoint(base_filename)
        start_page = last_page_from_checkpoint + 1
        print(f"📄 Last scraped page: {last_page_from_checkpoint}")
        if last_url:
            print(f"🔗 Last scraped URL: {last_url}")
        if last_page_from_checkpoint == 0:
            print("🆕 No existing progress found, starting fresh")

    # Ensure diagnostics directory exists when debugging
    if debug:
        os.makedirs(save_diagnostics_dir, exist_ok=True)

    async with async_playwright() as p:
        # Use simple browser setup that we know works
        browser = await p.chromium.launch(headless=not debug)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        visited_count = 0
        stop_all = False

        # small helper to write files off the event loop
        def _write_file_sync(path, content):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

        # safe filename generator for diagnostics (Windows-safe)
        def _safe_name(u: str) -> str:
            # strip scheme
            if u.startswith(URL_SCHEME):
                u = u[len(URL_SCHEME):]
            # replace any character that is not alphanumeric, dot, underscore, or dash
            return re.sub(r"[^A-Za-z0-9_.-]", "_", u)

        # Generate base filename from URL
        base_filename = generate_filename_from_url(topic_url)

        # incremental save function to save after each question
        async def _save_results_incrementally(accepted_list, no_accepted_list):
            # Ensure scrapped_data directory exists
            scrapped_data_dir = "scrapped_data"
            os.makedirs(scrapped_data_dir, exist_ok=True)
            
            # Save JSON files with dynamic names in scrapped_data directory
            accepted_json_file = os.path.join(scrapped_data_dir, f"{base_filename}_accepted.json")
            no_accepted_json_file = os.path.join(scrapped_data_dir, f"{base_filename}_no_accepted.json")
            
            await asyncio.to_thread(_write_file_sync, accepted_json_file, 
                                  json.dumps(accepted_list, indent=4, ensure_ascii=False))
            await asyncio.to_thread(_write_file_sync, no_accepted_json_file, 
                                  json.dumps(no_accepted_list, indent=4, ensure_ascii=False))
            
            # Create enhanced Excel with detailed response data
            excel_rows = []
            
            # Process accepted results
            for a in accepted_list:
                url = a.get('url')
                
                # Format question images
                question_images_info = ""
                if a.get('question_images'):
                    image_files = [img['filename'] for img in a.get('question_images', [])]
                    question_images_info = "; ".join(image_files)
                
                # Format all responses with details
                responses_summary = ""
                accepted_responses = ""
                other_responses = ""
                
                if a.get('all_responses'):
                    all_resp_texts = []
                    accepted_resp_texts = []
                    other_resp_texts = []
                    
                    for resp in a.get('all_responses', []):
                        resp_text = f"[{resp.get('author', 'Unknown')}] {resp.get('text', '')[:200]}..."
                        if resp.get('images'):
                            img_count = len(resp.get('images', []))
                            resp_text += f" [{img_count} image(s)]"
                        
                        all_resp_texts.append(resp_text)
                        
                        if resp.get('is_accepted'):
                            accepted_resp_texts.append(resp_text)
                        else:
                            other_resp_texts.append(resp_text)
                    
                    responses_summary = " | ".join(all_resp_texts)
                    accepted_responses = " | ".join(accepted_resp_texts)
                    other_responses = " | ".join(other_resp_texts)
                
                row = {
                    'page_number': a.get('page_number', ''),
                    'system': a.get('system', ''),
                    'title': a.get('title', ''),
                    'question': a.get('question', ''),
                    'question_images': question_images_info,
                    'total_responses': a.get('total_responses', 0),
                    'accepted_responses': accepted_responses,
                    'other_responses': other_responses,
                    'all_responses_summary': responses_summary,
                    'tags': "; ".join(a.get('tags', [])) if a.get('tags') else '',
                    'url': url,
                    'has_accepted_answer': 'Yes'
                }
                excel_rows.append(row)

            # Process no_accepted results  
            for n in no_accepted_list:
                url = n.get('url')
                
                # Check if this URL already exists (shouldn't happen but safety check)
                existing_row = next((row for row in excel_rows if row['url'] == url), None)
                if existing_row:
                    continue  # Skip duplicates
                
                # Format question images
                question_images_info = ""
                if n.get('question_images'):
                    image_files = [img['filename'] for img in n.get('question_images', [])]
                    question_images_info = "; ".join(image_files)
                
                # Format all responses
                responses_summary = ""
                if n.get('all_responses'):
                    all_resp_texts = []
                    for resp in n.get('all_responses', []):
                        resp_text = f"[{resp.get('author', 'Unknown')}] {resp.get('text', '')[:200]}..."
                        if resp.get('images'):
                            img_count = len(resp.get('images', []))
                            resp_text += f" [{img_count} image(s)]"
                        all_resp_texts.append(resp_text)
                    responses_summary = " | ".join(all_resp_texts)
                
                row = {
                    'page_number': n.get('page_number', ''),
                    'system': n.get('system', ''),
                    'title': n.get('title', ''),
                    'question': n.get('question', ''),
                    'question_images': question_images_info,
                    'total_responses': n.get('total_responses', 0),
                    'accepted_responses': '',
                    'other_responses': responses_summary,
                    'all_responses_summary': responses_summary,
                    'tags': "; ".join(n.get('tags', [])) if n.get('tags') else '',
                    'url': url,
                    'has_accepted_answer': 'No'
                }
                excel_rows.append(row)

            if excel_rows:
                df = pd.DataFrame(excel_rows)
                # Save Excel file with enhanced data in scrapped_data directory
                excel_filename = os.path.join(scrapped_data_dir, f"{base_filename}.xlsx")
                await asyncio.to_thread(df.to_excel, excel_filename, index=False)
                print(f"💾 Saved: {len(accepted_list)} accepted, {len(no_accepted_list)} no_accepted | Total rows: {len(df)} | File: {excel_filename}")
            else:
                print("💾 No data to save to Excel yet")

        # Loop over paginated question lists
        for page_num in range(start_page, max_pages + 1):
            url = f"{topic_url}?page={page_num}"
            print(f"🔍 Scraping question list: {url} (Page {page_num}/{max_pages})")
            # Save checkpoint before processing each page
            save_progress_checkpoint(base_filename, page_num, url)
            print(f"[DEBUG] Saved checkpoint for page {page_num} and url {url}")
            # Add random delay to avoid rate limiting
            await page.wait_for_timeout(2000 + (page_num * 1000))
            # Try multiple times if blocked
            success = False
            for attempt in range(3):
                try:
                    await page.goto(url, timeout=60000)
                    await page.wait_for_timeout(3000)
                    # Check if we got a 403 or similar error page
                    title = await page.title()
                    if "403" in title or "Forbidden" in title or "Access Denied" in title:
                        print(f"⚠️ Attempt {attempt + 1}: Got blocked (403), waiting before retry...")
                        if attempt < 2:  # Don't wait on last attempt
                            await page.wait_for_timeout(10000 + (attempt * 5000))  # Progressive delays
                        continue
                    
                    success = True
                    break
                    
                except Exception as e:
                    print(f"⚠️ Attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await page.wait_for_timeout(5000)
            
            if not success:
                print(f"❌ Failed to load page {page_num} after 3 attempts. Skipping...")
                continue

            # Give the page more time to render client-side content (especially in headless mode)
            await page.wait_for_timeout(3000)

            # Wait for question anchors (site renders client-side). Prefer thread link patterns.
            try:
                await page.wait_for_selector("a[href*='/qaq-p/'], a[href*='/qaa-p/'], a[href*='/qa-p/']", timeout=10000)
            except TimeoutError:
                # continue to attempt to find links even if the wait times out
                pass

            # Grab all question links on page using thread patterns first
            question_links = await page.query_selector_all("a[href*='/qaq-p/'], a[href*='/qaa-p/'], a[href*='/qa-p/']")
            print(f"Found {len(question_links)} thread pattern links")
            if not question_links:
                # fallback: elements that look like titles or any /t5/ links
                question_links = await page.query_selector_all("a.question-title")
                print(f"Fallback: Found {len(question_links)} .question-title links")
            if not question_links:
                question_links = await page.query_selector_all("a[href*='/t5/']")
                print(f"Fallback: Found {len(question_links)} /t5/ links")

            q_urls = []
            for q in question_links:
                href = await q.get_attribute("href")
                if href:
                    q_urls.append(href)

            # Filter links: keep only question/thread pages and exclude profiles/boards
            filtered = []
            for href in q_urls:
                # normalize to full URL for easier checks
                full = href if href.startswith('http') else 'https://community.sap.com' + href
                # skip profile and non-thread pages
                if '/user/viewprofilepage' in full:
                    continue
                # only accept common question thread patterns (SAP Community uses -p segments)
                if re.search(r'/t5/.+/(?:qaq|qaa|qa)-p/', full):
                    filtered.append(full)

            # deduplicate while preserving order
            seen = set()
            q_urls = []
            for u in filtered:
                if u not in seen:
                    seen.add(u)
                    q_urls.append(u)

            print(f"After filtering: {len(q_urls)} valid question URLs to visit")
            
            # Smart stopping: if no valid URLs found, we've reached the end
            if len(q_urls) == 0:
                print(f"🛑 No more questions found on page {page_num}. Stopping pagination.")
                break
            
            # Debug: save page content when no links found
            if len(q_urls) == 0 and debug == False:
                print("⚠️ No links found - saving page snapshot for debugging")
                content = await page.content()
                fname = f"debug_no_links_page_{page_num}.html"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Saved debug snapshot: {fname}")

            # Visit each question page
            for q_url in q_urls:
                # stop if we've hit the max_questions limit
                if max_questions is not None and visited_count >= max_questions:
                    stop_all = True
                    break
                if not q_url.startswith("http"):
                    q_url = "https://community.sap.com" + q_url

                print(f"➡️ Visiting: {q_url}")
                # Attempt navigation with a single retry on aborts/timeouts
                goton_ok = False
                for attempt in range(2):
                    try:
                        await page.goto(q_url, timeout=60000)
                        await page.wait_for_timeout(500)
                        goton_ok = True
                        break
                    except Exception as e:
                        print(f"Navigation attempt {attempt+1} failed for {q_url}: {e}")
                        # wait briefly before retry
                        await page.wait_for_timeout(1000)

                if not goton_ok:
                    print(f"❌ Failed to navigate to {q_url} after retries.")
                    if debug:
                        try:
                            content = await page.content()
                            safe_name = _safe_name(q_url)
                            fname = os.path.join(save_diagnostics_dir, f"nav_error_{safe_name}.html")
                            await asyncio.to_thread(_write_file_sync, fname, content)
                        except Exception:
                            pass
                    # skip this question
                    continue

                try:
                    # Title - try multiple selectors for SAP Community
                    title = ""
                    title_selectors = [
                        ".lia-message-subject h1",
                        ".lia-message-subject .lia-message-subject-content", 
                        ".lia-message-subject",
                        "h1.PageTitle",
                        "h1"
                    ]
                    for sel in title_selectors:
                        if await page.query_selector(sel):
                            title = await page.inner_text(sel)
                            title = title.strip()
                            if title:
                                break
                    
                    # Extract from page title as fallback
                    if not title:
                        page_title = await page.title()
                        if page_title and " | SAP Community" in page_title:
                            title = page_title.replace(" | SAP Community", "").strip()

                    # Question body - try a few common selectors including LIA markup
                    question_body = ""
                    question_images = []
                    
                    for sel in ("#bodyDisplay", "div.lia-message-body", "div.question-body", "div.thread-body", "div.msgBody", "div.pure-u-1-1"):
                        if await page.query_selector(sel):
                            question_element = await page.query_selector(sel)
                            question_body = await question_element.inner_text()
                            
                            # Extract images from question
                            base_filename = generate_filename_from_url(q_url)
                            images_dir = os.path.join("scrapped_data", "images", base_filename)
                            question_images = await extract_images_from_element(page, question_element, q_url, images_dir)
                            break

                    # Tags - extract from meta tags and LIA elements
                    tags = []
                    
                    # Method 1: Extract from meta property article:tag
                    meta_tags = await page.query_selector_all('meta[property="article:tag"]')
                    for meta in meta_tags:
                        content = await meta.get_attribute("content")
                        if content and content.strip():
                            tags.append(content.strip())
                    
                    # Method 2: Try LIA tag elements
                    if not tags:
                        tag_elements = await page.query_selector_all("a.topic-tag, .lia-tag, .lia-tags a")
                        for t in tag_elements:
                            tag_text = await t.inner_text()
                            if tag_text and tag_text.strip():
                                tags.append(tag_text.strip())

                    # System/module - extract from meta property article:section or breadcrumbs
                    system = ""
                    
                    # Method 1: Extract from meta article:section
                    section_meta = await page.query_selector('meta[property="article:section"]')
                    if section_meta:
                        system = await section_meta.get_attribute("content")
                        if system:
                            system = system.strip()
                    
                    # Method 2: Try breadcrumb or navigation elements
                    if not system:
                        breadcrumb_selectors = [
                            ".lia-breadcrumb-navigation a",
                            ".breadcrumb a", 
                            "nav a",
                            ".lia-component-common-widget-breadcrumb a"
                        ]
                        for sel in breadcrumb_selectors:
                            breadcrumbs = await page.query_selector_all(sel)
                            if len(breadcrumbs) > 1:  # Usually home > section > subsection
                                # Take the second-to-last breadcrumb as system
                                system = await breadcrumbs[-2].inner_text()
                                system = system.strip()
                                if system:
                                    break

                    # Extract ALL responses from the page (with images)
                    all_responses = await extract_all_responses(page)
                    
                    # Find accepted response(s)
                    accepted_responses = [r for r in all_responses if r['is_accepted']]
                    non_accepted_responses = [r for r in all_responses if not r['is_accepted']]
                    
                    # Create base result entry
                    base_result = {
                        'page_number': page_num,
                        'system': system,
                        'title': title,
                        'question': question_body,
                        'question_images': question_images,
                        'tags': tags,
                        'url': q_url,
                        'total_responses': len(all_responses),
                        'all_responses': all_responses
                    }
                    
                    if accepted_responses:
                        # If there are accepted responses, save as accepted
                        result_entry = base_result.copy()
                        result_entry['accepted_responses'] = accepted_responses
                        result_entry['non_accepted_responses'] = non_accepted_responses
                        result_entry['primary_accepted_response'] = accepted_responses[0]['text']  # For backward compatibility
                        
                        accepted_results.append(result_entry)
                        visited_count += 1
                        
                        print(f"✅ Found {len(accepted_responses)} accepted response(s) and {len(non_accepted_responses)} other response(s)")
                        
                        # Save immediately after each extraction
                        await _save_results_incrementally(accepted_results, no_accepted_results)
                        
                        # Save checkpoint after successful scraping
                        save_progress_checkpoint(base_filename, page_num, q_url)
                        
                        # Check if we've hit the max_questions limit
                        if max_questions is not None and visited_count >= max_questions:
                            stop_all = True
                            break
                    else:
                        # No accepted responses, save as no_accepted
                        result_entry = base_result.copy()
                        result_entry['non_accepted_responses'] = non_accepted_responses
                        result_entry['primary_response'] = non_accepted_responses[0]['text'] if non_accepted_responses else ""  # For backward compatibility
                        
                        no_accepted_results.append(result_entry)
                        visited_count += 1

                        print(f'⚠️ No accepted answer found. Found {len(non_accepted_responses)} other response(s)')
                        
                        # Save immediately after each extraction
                        await _save_results_incrementally(accepted_results, no_accepted_results)
                        
                        # Save checkpoint after successful scraping
                        save_progress_checkpoint(base_filename, page_num, q_url)
                        
                        # Check if we've hit the max_questions limit
                        if max_questions is not None and visited_count >= max_questions:
                            stop_all = True
                            break
                        if debug:
                            safe_name = _safe_name(q_url)
                            fname = os.path.join(save_diagnostics_dir, f'no_accepted_{safe_name}.html')
                            content = await page.content()
                            await asyncio.to_thread(_write_file_sync, fname, content)

                except Exception as e:
                    print(f"Error parsing {q_url}: {e}")
                    if debug:
                        safe_name = _safe_name(q_url)
                        fname = os.path.join(save_diagnostics_dir, f"error_{safe_name}.html")
                        try:
                            content = await page.content()
                            await asyncio.to_thread(_write_file_sync, fname, content)
                        except Exception:
                            pass

            # Check if we need to stop processing more pages
            if stop_all:
                break

        await browser.close()

    return accepted_results, no_accepted_results


if __name__ == "__main__":
    # SAP Community scraper with full pagination support and resume capability
    topic_url = "https://community.sap.com/t5/crm-and-cx-q-a/qa-p/crm-questions"

    # Production settings:
    # - max_pages: Set to high number (999) for unlimited scraping - will auto-stop when no more pages found
    # - debug: Set to False for faster headless scraping (True to see browser)
    # - max_questions: None for unlimited questions per run
    # - resume: True to continue from last scraped position, False to start fresh
    
    # Generate filename for this URL
    base_filename = generate_filename_from_url(topic_url)
    
    # Uncomment the next line to reset all progress and start fresh
    # reset_progress(base_filename)
    
    print("🚀 Starting SAP Community scraper with pagination and resume capability...")
    print(f"📄 Target: {topic_url}")
    print("📁 Output directory: scrapped_data/")
    print(f"📁 Output files: scrapped_data/{base_filename}.*")
    print("⚙️ Settings: UNLIMITED pages, headless mode, unlimited questions, RESUME enabled")
    print("💾 Output: Excel file with incremental saving")
    print("🔄 Resume: Will automatically skip already scraped URLs")
    print("💡 To start fresh, uncomment the reset_progress() line in the script")
    print("=" * 70)
    
    accepted, no_accepted = asyncio.run(scrape_sap_community(
        topic_url, 
        max_pages=999,       # Set very high number for unlimited scraping
        debug=False,         # Headless mode for faster scraping
        max_questions=None,  # No limit on questions
        resume=True          # Enable resume functionality
    ))

    print("=" * 70)
    print("✅ Scraping complete!")
    print(f"📊 Results: {len(accepted)} accepted answers, {len(no_accepted)} questions without accepted answers")
    print(f"📊 Total unique questions processed: {len(accepted) + len(no_accepted)}")
    print("📁 Files created/updated in scrapped_data/:")
    print(f"   - {base_filename}_accepted.json (accepted answers)")
    print(f"   - {base_filename}_no_accepted.json (questions without accepted answers)")
    print(f"   - {base_filename}.xlsx (Excel with merged data)")
    print(f"   - {base_filename}_checkpoint.json (progress checkpoint)")
    print("💡 Excel file contains all data with page numbers and incremental updates")
    print("🖼️ Images are saved in scrapped_data/images/ subdirectory")
