"""
SAP Community Scraper - Multiple URL Example
This script shows how to scrape different SAP Community sections with automatic filename generation.
"""

import asyncio
from script import scrape_sap_community, generate_filename_from_url

async def scrape_multiple_sections():
    """Example of scraping multiple SAP Community sections"""
    
    # Define different SAP Community sections to scrape
    urls_to_scrape = [
        {
            "name": "Supply Chain Management",
            "url": "https://community.sap.com/t5/supply-chain-management-q-a/qa-p/scm-questions",
            "pages": 3
        },
        {
            "name": "Technology", 
            "url": "https://community.sap.com/t5/technology-q-a/qa-p/technology-questions",
            "pages": 2
        },
        {
            "name": "Financial Management",
            "url": "https://community.sap.com/t5/financial-management-q-a/qa-p/financial-management-questions", 
            "pages": 2
        }
    ]
    
    print("🚀 SAP Community Multi-Section Scraper")
    print("=" * 70)
    
    for section in urls_to_scrape:
        print(f"\n📋 Processing: {section['name']}")
        print(f"🔗 URL: {section['url']}")
        
        # Generate filename for this section
        filename = generate_filename_from_url(section['url'])
        print(f"📁 Output files: {filename}.*")
        print(f"📄 Pages to scrape: {section['pages']}")
        print("-" * 50)
        
        try:
            # Scrape this section
            accepted, no_accepted = await scrape_sap_community(
                section['url'],
                max_pages=section['pages'],
                debug=False,  # Headless mode for faster scraping
                max_questions=None  # No limit
            )
            
            print(f"✅ {section['name']} completed!")
            print(f"📊 Results: {len(accepted)} accepted, {len(no_accepted)} no_accepted")
            print(f"📁 Files: {filename}.xlsx, {filename}_accepted.json, {filename}_no_accepted.json")
            
        except Exception as e:
            print(f"❌ Error scraping {section['name']}: {e}")
        
        print("=" * 70)
    
    print("🎉 All sections processed!")

if __name__ == "__main__":
    asyncio.run(scrape_multiple_sections())
