import json
from pathlib import Path
from PIL import Image
import io

# Path configuration
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"

# Load tarot cards
with open(DATA_DIR / 'tarot_cards.json', 'r', encoding='utf-8') as f:
    TAROT_CARDS = json.load(f)

def check_card_images():
    """Check all cards and their images"""
    print("="*60)
    print("CHECKING TAROT CARDS AND IMAGES")
    print("="*60)
    
    # Sort cards
    TAROT_CARDS.sort(key=lambda x: (
        x['arcana'] != 'major',  # Majors first
        x.get('suit', ''), 
        x['number']
    ))
    
    missing_images = []
    found_images = []
    
    for card in TAROT_CARDS:
        card_name = card['name']
        number = card.get('number', 0)
        suit = card.get('suit', 'major')
        
        # Try multiple filename patterns
        safe_name = card_name.lower().replace(' ', '_').replace('_of_', '_')
        
        patterns = [
            f"{number:02d}_{safe_name}.jpg",
            f"{number:02d}_{safe_name}.jpeg",
            f"{number:02d}_{safe_name}.png",
            f"{safe_name}.jpg",
            f"{safe_name}.jpeg",
            f"{safe_name}.png",
            f"{card_name.replace(' ', '').replace('_', '').lower()}.jpg",
            f"{card_name.replace(' ', '').replace('_', '').lower()}.png"
        ]
        
        found = False
        image_path = None
        
        for pattern in patterns:
            path = IMAGES_DIR / pattern
            if path.exists():
                found = True
                image_path = path
                found_images.append(card_name)
                break
        
        status = "✅ FOUND" if found else "❌ MISSING"
        arcana_type = "MAJOR" if card['arcana'] == 'major' else f"MINOR ({suit})"
        
        print(f"[{status}] {card_name:<25} | #{number:02d} | {arcana_type}")
        
        if found and image_path:
            try:
                # Try to open image
                img = Image.open(image_path)
                print(f"       ↳ Image: {image_path.name} ({img.size[0]}x{img.size[1]}, {img.format})")
            except Exception as e:
                print(f"       ↳ Error opening: {e}")
        
        if not found:
            missing_images.append(card_name)
            # Show what filenames were checked
            print(f"       ↳ Checked: {patterns[0]}, {patterns[3]}, ...")
    
    print("\n" + "="*60)
    print(f"SUMMARY:")
    print(f"Total Cards: {len(TAROT_CARDS)}")
    print(f"Images Found: {len(found_images)}")
    print(f"Images Missing: {len(missing_images)}")
    print(f"Coverage: {(len(found_images)/len(TAROT_CARDS)*100):.1f}%")
    
    if missing_images:
        print("\nMISSING IMAGES:")
        for i, card in enumerate(missing_images[:20]):  # Show first 20
            print(f"  {i+1}. {card}")
        if len(missing_images) > 20:
            print(f"  ... and {len(missing_images)-20} more")
    
    print("\nSUGGESTED FILENAMES:")
    print("For Major Arcana:")
    print("  00_the_fool.jpg, 01_the_magician.jpg, etc.")
    print("\nFor Minor Arcana:")
    print("  01_wands.jpg, 02_wands.jpg, etc.")
    print("  OR: ace_of_wands.jpg, two_of_wands.jpg, etc.")

def display_card_image(card_name: str):
    """Display a specific card's image"""
    from PIL import Image, ImageDraw, ImageFont
    import matplotlib.pyplot as plt
    
    # Find the card
    card_data = None
    for card in TAROT_CARDS:
        if card['name'].lower() == card_name.lower():
            card_data = card
            break
    
    if not card_data:
        print(f"Card '{card_name}' not found!")
        return
    
    print(f"\nChecking card: {card_data['name']}")
    print(f"Number: {card_data.get('number', 'N/A')}")
    print(f"Arcana: {card_data['arcana']}")
    if card_data.get('suit'):
        print(f"Suit: {card_data['suit']}")
    
    # Try to find image
    safe_name = card_data['name'].lower().replace(' ', '_').replace('_of_', '_')
    patterns = [
        f"{card_data.get('number', 0):02d}_{safe_name}.jpg",
        f"{card_data.get('number', 0):02d}_{safe_name}.png",
        f"{safe_name}.jpg",
        f"{safe_name}.png",
    ]
    
    image_path = None
    for pattern in patterns:
        path = IMAGES_DIR / pattern
        if path.exists():
            image_path = path
            break
    
    if image_path:
        print(f"\n✅ Image found: {image_path.name}")
        
        # Open and display image
        img = Image.open(image_path)
        print(f"   Size: {img.size[0]}x{img.size[1]}")
        print(f"   Format: {img.format}")
        print(f"   Mode: {img.mode}")
        
        # Show image
        plt.figure(figsize=(8, 10))
        plt.imshow(img)
        plt.title(f"{card_data['name']}\n{image_path.name}")
        plt.axis('off')
        plt.show()
        
        # Show in console (ASCII art if small)
        if img.size[0] <= 100:
            img_small = img.resize((40, 60))
            img_gray = img_small.convert('L')
            
            ascii_chars = "@%#*+=-:. "
            print("\nASCII Preview:")
            for y in range(img_gray.height):
                line = ""
                for x in range(img_gray.width):
                    pixel = img_gray.getpixel((x, y))
                    line += ascii_chars[pixel * len(ascii_chars) // 256]
                print(line)
    else:
        print(f"\n❌ No image found for {card_data['name']}")
        print("Tried patterns:")
        for pattern in patterns:
            print(f"  - {pattern}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # Check specific card
        card_name = " ".join(sys.argv[1:])
        display_card_image(card_name)
    else:
        # Check all cards
        check_card_images()