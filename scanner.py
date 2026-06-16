import os
import requests
from bs4 import BeautifulSoup

def analyze_auction_entry(title, description):
    text = f"{title} {description}".lower()
    
    # Structural Flags
    green_flags = ["frames tight", "structurally sound", "sturdy", "tight joints", "no wobble"]
    red_flags = ["wobble", "loose joint", "unstable", "needs repair", "frame damage", "wobbly"]
    cosmetic_notes = ["worn cord", "papercord stained", "needs reweaving", "as-is cord"]
    
    has_green = any(flag in text for flag in green_flags)
    has_red = any(flag in text for flag in red_flags)
    needs_cord = any(note in text for note in cosmetic_notes)
    
    if has_red:
        return "SKIP", "🚨 Structural Red Flag: Frame integrity compromised."
    elif has_green:
        if needs_cord:
            return "HIGH 🔥", "✅ Frame Tight / 🧶 Cord Worn. Ideal restoration target."
        return "CRITICAL ⭐", "✅ Frame Tight / Cord Intact. Pristine condition."
    return "STANDARD", "❓ Ambiguous: No explicit structural keywords found."

def run_search():
    print("Searching eBay for Møller chairs...")
    # Target search for Møller 77 and 57
    url = "https://www.ebay.com/sch/i.html?_nkw=niels+moller+77+57+teak"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")
    listings = soup.find_all("div", class_="s-item__info")
    
    for item in listings[:5]: # Check the first 5 recent items
        title_element = item.find("div", class_="s-item__title")
        price_element = item.find("span", class_="s-item__price")
        link_element = item.find("a", class_="s-item__link")
        
        if title_element and price_element:
            title = title_element.text.strip()
            price = price_element.text.strip()
            link = link_element["href"] if link_element else "#"
            
            # Skip the default eBay placeholder result
            if "shop on ebay" in title.lower():
                continue
                
            # Analyze the title text for our flags
            priority, flag_note = analyze_auction_entry(title, "")
            
            if priority != "SKIP":
                print(f"\n=== MATCH FOUND ({priority}) ===")
                print(f"📌 {title}")
                print(f"💰 {price}")
                print(f"🔍 [FLAG REPORT]: {flag_note}")
                print(f"🔗 {link}\n")

if __name__ == "__main__":
    run_search()
