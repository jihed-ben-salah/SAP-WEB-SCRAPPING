import asyncio, json
from script import scrape_sap_community

if __name__ == '__main__':
    topic = "https://community.sap.com/t5/supply-chain-management-q-a/qa-p/scm-questions"
    accepted, no_accepted = asyncio.run(scrape_sap_community(topic, max_pages=1, debug=True, max_questions=5))
    print("SCRAPED: accepted=", len(accepted), " no_accepted=", len(no_accepted))
    with open("tmp_output_accepted.json", "w", encoding="utf-8") as f:
        json.dump(accepted, f, ensure_ascii=False, indent=2)
    with open("tmp_output_no_accepted.json", "w", encoding="utf-8") as f:
        json.dump(no_accepted, f, ensure_ascii=False, indent=2)
