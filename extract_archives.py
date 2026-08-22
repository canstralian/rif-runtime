#!/usr/bin/env python3
"""
Extract ADR and specification ZIP archives from GitHub and organize into docs/.

Usage:
    python extract_archives.py

This script:
1. Downloads rif-runtime-adrs.zip from GitHub
2. Extracts contents into docs/adrs/
3. Downloads rif-runtime-specification-docs.zip from GitHub
4. Extracts contents into docs/specifications/
"""

import io
import zipfile
from pathlib import Path
from urllib.request import urlopen
import sys


def download_and_extract(zip_url: str, target_dir: str) -> None:
    """Download a ZIP from URL and extract contents.
    
    Args:
        zip_url: Full GitHub raw or download URL to ZIP file
        target_dir: Directory to extract contents into
        
    Raises:
        urllib.error.URLError: If download fails
        zipfile.BadZipFile: If ZIP is corrupted
    """
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading: {zip_url}")
    try:
        with urlopen(zip_url) as response:
            zip_data = io.BytesIO(response.read())
        
        print(f"Extracting to: {target_path.absolute()}")
        with zipfile.ZipFile(zip_data, 'r') as z:
            z.extractall(target_path)
            print(f"  Extracted {len(z.namelist())} files:")
            for name in sorted(z.namelist()):
                print(f"    - {name}")
                
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        raise


def main():
    """Main extraction workflow."""
    
    repo_base = "https://raw.githubusercontent.com/canstralian/rif-runtime/main"
    
    # ADRs
    print("\n" + "="*60)
    print("📋 Extracting Architecture Decision Records (ADRs)")
    print("="*60)
    download_and_extract(
        f"{repo_base}/rif-runtime-adrs.zip",
        "docs/adrs"
    )
    
    # Specifications
    print("\n" + "="*60)
    print("📚 Extracting System Specifications")
    print("="*60)
    download_and_extract(
        f"{repo_base}/rif-runtime-specification-docs.zip",
        "docs/specifications"
    )
    
    print("\n" + "="*60)
    print("✅ Extraction complete!")
    print("="*60)
    print("\nNext steps:")
    print("  1. Review extracted files in docs/adrs/ and docs/specifications/")
    print("  2. Update docs/DOCUMENTATION_INDEX.md with actual file references")
    print("  3. Commit changes to the docs/extract-adrs branch")
    print("  4. Create a pull request to main")


if __name__ == "__main__":
    main()
