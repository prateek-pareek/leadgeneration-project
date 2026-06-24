import os

def replace_in_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if 'primebytelabs' not in content.lower():
            return
            
        new_content = content.replace('PrimeByteLabs', 'AcmeCorp')
        new_content = new_content.replace('primebyteLabs', 'acmecorp')
        new_content = new_content.replace('primebytelabs', 'acmecorp')
        new_content = new_content.replace('PrimebyteLabs', 'Acmecorp')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
    except Exception as e:
        print(f"Failed to process {filepath}: {e}")

def main():
    exclude_dirs = {'.git', 'node_modules', '.next', 'dist', 'build'}
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file.startswith('search_results') or file == 'bulk_replace.py':
                continue
            filepath = os.path.join(root, file)
            replace_in_file(filepath)

if __name__ == "__main__":
    main()
