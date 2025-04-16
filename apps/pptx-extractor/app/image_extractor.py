import subprocess
import shlex
from pathlib import Path
from pdf2image import convert_from_path

def convert_pptx_to_images(pptx_path: Path, output_dir: Path, image_format="png"):
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Convert PPTX to PDF
    pdf_path = pptx_path.with_suffix(".pdf")
    try:
        cmd = f"libreoffice --headless --convert-to pdf {shlex.quote(str(pptx_path))} --outdir {shlex.quote(str(pptx_path.parent))}"
        print("🛠 Running command:", cmd)

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        print("✅ stdout:", result.stdout)
        print("❌ stderr:", result.stderr)

        if result.returncode != 0:
            raise RuntimeError("LibreOffice PDF conversion failed")

    except Exception as e:
        print(f"❌ LibreOffice conversion failed: {e}")
        raise

    if not pdf_path.exists():
        print("❌ PDF was not created after LibreOffice conversion")
        raise FileNotFoundError(f"Expected PDF not found at {pdf_path}")

    # Step 2: Convert PDF to images
    images = convert_from_path(str(pdf_path))
    print(f"✅ {len(images)} slides extracted from PDF")

    for i, img in enumerate(images, start=1):
        img.save(output_dir / f"slide_{i:02d}.{image_format}")

    return sorted(output_dir.glob(f"slide_*.{image_format}"))
