# @Author: Christian Blank <git@cyneric.de>
# @License: Open Source (GPL3)

# python script to run recursively over a folder and its subfolders to extract isbns from epub files and download book cover and place them besides the epub files named as cover.jpg

# dependencies: BeautifulSoup, requests, lxml (pip install them if you don't have them already)
# to install dependencies run: "pip install beautifulsoup4 requests lxml" (or pip3 if you are using python3)

# Usage: python getBookCovers.py <path to folder>


import hashlib
import os
import zipfile
from bs4 import BeautifulSoup
import requests
import sys
import json
import re

GOOGLE_BOOKS_API_KEY = ""  # your google books api key here *optional*


# Search the directory and its subfolders for EPUB files
def search_directory(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            cover_path = os.path.join(root, "cover.jpg")

            if file.endswith(".epub"):
                epub_path = os.path.join(root, file)

                print(f"\033[94m Started processing file: {os.path.basename(epub_path)}\033[0m")

                if os.path.isfile(cover_path):
                    print("\033[93m\t- cover already exists, skipping download\033[0m")
                    print("_____________________________________________\n")
                    continue

                isbn = extract_isbn(epub_path)
                if isbn:
                    print(f"\t- get cover for isbn: \033[96m{isbn}\033[0m")
                    download_cover(isbn, cover_path)
                    print("_____________________________________________\n")


# Download the book cover based on the ISBN
def download_cover(isbn, output_path):
    response = get_cover_from_buch_isbn_de(isbn)
    if response is None:
        response = get_cover_from_openlibrary(isbn)
        if response is None:
            response = get_cover_from_google_books(isbn)
            if response is None:
                print("\033[91m\t- no cover found\033[0m")
                return

    save_cover(response, output_path)


# Extract the ISBN from the EPUB file
def extract_isbn(epub_path):
    print("\t- extracting isbn fom .epub container")

    try:
        with zipfile.ZipFile(epub_path, "r") as myzip:
            for file in myzip.namelist():
                if file.endswith(".opf"):
                    data = myzip.read(file).decode("utf-8")
                    soup = BeautifulSoup(data, "xml")
                    isbn_node = soup.find("dc:identifier", attrs={"opf:scheme": "ISBN"})
                    if isbn_node:
                        isbn = isbn_node.text
                        if isbn.startswith("urn:isbn:"):
                            isbn = isbn[9:]
                        print(f"\t- found: \033[96m{isbn}\033[0m")
                        return isbn
                    else:
                        print("\033[91m\t- no isbn found\033[0m")
                        title_node = soup.find("dc:title")
                        if title_node:
                            title = title_node.text
                            print(f"\t- trying to find isbn by title: \033[96m{title}\033[0m")
                            author = os.path.dirname(epub_path).split(os.path.sep)[2]
                            match = re.search(r"\((.*?)\)", os.path.dirname(epub_path))
                            year = match.group(1) if match else None
                            isbn = get_isbn_from_title(author, title, year, GOOGLE_BOOKS_API_KEY)
                            if isbn:
                                print(f"\t- found: \033[96m{isbn}\033[0m")
                                return isbn
                            else:
                                print("\033[91m\t- no isbn found for title\033[0m")
    except FileNotFoundError:
        print("\033[91m\t- File not found: \033[0m" + epub_path)

    print("_____________________________________________\n")
    return None


# Get the ISBN from the Google Books API based on the title, author, and year
def get_isbn_from_title(author, title, year, api_key):
    query = f"https://www.googleapis.com/books/v1/volumes?q={title}"
    if author:
        query += f" {author}"
    if year:
        query += f" ({year})"
    if api_key:
        query += f"&key={api_key}"
    print(f"\t- request: \033[96m{query}\033[0m")
    response = requests.get(query)
    data = json.loads(response.text)
    if "items" in data:
        for item in data["items"]:
            if "industryIdentifiers" in item["volumeInfo"]:
                for identifier in item["volumeInfo"]["industryIdentifiers"]:
                    if identifier["type"] == "ISBN_13":
                        return identifier["identifier"]
    return None


# Download the book cover from buch.isbn.de
def get_cover_from_buch_isbn_de(isbn):
    url = f"https://buch.isbn.de/gross/{isbn}.jpg"
    print(f"\t- downloading from url: \033[96m{url}\033[0m")
    response = requests.get(url)
    md5_hash = hashlib.md5()
    md5_hash.update(response.content)
    if md5_hash.hexdigest() == "f81b2d84d8a69ba9e8bf1f50c806faab":
        print("\033[93m\t- generic cover image detected, skipping\033[0m")
        return None
    if response.status_code != 200:
        return None
    return response.content


# Download the book cover from openlibrary.org
def get_cover_from_openlibrary(isbn):
    url = f"http://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
    print(f"\t- downloading from url: \033[96m{url}\033[0m")
    response = requests.get(url)
    md5_hash = hashlib.md5()
    md5_hash.update(response.content)
    if md5_hash.hexdigest() == "0d23d0b62908b75e89014ac3f864484e":
        print("\033[93m\t- generic cover image detected, skipping\033[0m")
        return None
    if response.status_code != 200:
        return None
    return response.content

# Download the book cover from google books
def get_cover_from_google_books(isbn):
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
    print(f"\t- downloading from url: \033[96m{url}\033[0m")
    response = requests.get(url)
    if response.status_code != 200:
        return None
    data = response.json()
    if "items" in data:
        image_links = data["items"][0]["volumeInfo"].get("imageLinks", {})
        if "thumbnail" in image_links:
            image_url = image_links["thumbnail"]
            response = requests.get(image_url)
            if response.status_code != 200:
                return None
            return response.content
    return None


# Save the cover to the output path
def save_cover(content, output_path):
    with open(output_path, "wb") as f:
        f.write(content)
        print(f"\033[1;92m\t- done! cover saved to: {output_path}\033[0m")


if len(sys.argv) != 2:
    print("Usage: python getBookCovers.py <path to folder>")
    sys.exit(1)

search_directory(sys.argv[1])