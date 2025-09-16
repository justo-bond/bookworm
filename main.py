from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import fitz  # PyMuPDF для парсинга PDF
import requests  # Для xAI API
import re  # Для детекции глав
from ebooklib import epub  # Адаптируем для FB2 (или используй fb2-py)
from xml.etree import ElementTree as ET  # Для ручной генерации FB2 XML
import tempfile
import os
from typing import List

app = FastAPI(title="PDF to Translated FB2 Service")

# Твой API-ключ xAI (Grok). Получи на x.ai/api
XAI_API_KEY = "your_xai_api_key_here"
XAI_API_URL = "https://api.x.ai/v1/chat/completions"  # Актуальный endpoint на 2025

def extract_text_from_pdf(pdf_path: str) -> str:
    """Извлекает весь текст из PDF."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text

def split_into_chapters(text: str) -> List[str]:
    """Разбивает текст на главы по заголовкам (эвристика)."""
    # Ищем паттерны вроде "Chapter 1", "Глава 1" или по TOC (если есть)
    chapters = re.split(r'(Chapter\s+\d+|Глава\s+\d+)', text, flags=re.IGNORECASE)
    # Объединяем заголовок с содержимым
    combined_chapters = []
    for i in range(0, len(chapters) - 1, 2):
        combined_chapters.append(chapters[i] + chapters[i+1])
    if len(chapters) % 2 == 1:
        combined_chapters.append(chapters[-1])
    return [chap.strip() for chap in combined_chapters if chap.strip()]

def translate_chapter(text: str, style: str = "в стиле Стругацких") -> str:
    """Переводит главу с помощью Grok API."""
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-4",  # Или актуальная модель на 2025
        "messages": [{"role": "user", "content": f"Переведи этот текст на русский {style}: {text[:4000]}"}],  # Ограничение по токенам
        "max_tokens": 4096
    }
    response = requests.post(XAI_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise ValueError("Ошибка перевода: " + response.text)
    return response.json()["choices"][0]["message"]["content"]

def generate_fb2(chapters: List[str], title: str = "Translated Book", author: str = "Unknown") -> str:
    """Генерирует FB2-файл из переведённых глав."""
    root = ET.Element("FictionBook", xmlns="http://www.gribuser.ru/xml/fictionbook/2.0")
    description = ET.SubElement(root, "description")
    title_info = ET.SubElement(description, "title-info")
    ET.SubElement(title_info, "book-title").text = title
    ET.SubElement(title_info, "author").text = author
    
    body = ET.SubElement(root, "body")
    for i, chap in enumerate(chapters):
        section = ET.SubElement(body, "section")
        ET.SubElement(section, "title").text = f"Глава {i+1}"
        p = ET.SubElement(section, "p")
        p.text = chap
    
    tree = ET.ElementTree(root)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".fb2") as tmp:
        tree.write(tmp.name, encoding="utf-8", xml_declaration=True)
        return tmp.name

@app.post("/translate-pdf-to-fb2/")
async def translate_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Только PDF файлы!")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
        tmp_pdf.write(await file.read())
        pdf_path = tmp_pdf.name
    
    try:
        full_text = extract_text_from_pdf(pdf_path)
        chapters = split_into_chapters(full_text)
        translated_chapters = []
        for chap in chapters:
            translated = translate_chapter(chap)  # Добавь стиль, если нужно: translate_chapter(chap, "в стиле Стругацких")
            translated_chapters.append(translated)
        
        fb2_path = generate_fb2(translated_chapters, title=file.filename.replace(".pdf", ""))
        
        return FileResponse(fb2_path, media_type="application/xml", filename="translated_book.fb2")
    finally:
        os.unlink(pdf_path)  # Чистим временные файлы

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
