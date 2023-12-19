# python script to run recursively over a folder and its subfolders to extract isbns from epub files and download book cover from openlibrary.org and place them besides the epub files named as cover.jpg

# dependencies: BeautifulSoup, requests, lxml (pip install them if you don't have them already)
# -> pip install beautifulsoup4 requests lxml (or pip3 if you are using python3)

# Usage: python getBookCovers.py <path to folder>


import hashlib
import os
import zipfile
from bs4 import BeautifulSoup
import requests
import sys
import json



GOOGLE_BOOKS_API_KEY = ""; # your google books api key here



# extracting isbn from .opf file inside the epub file
def extract_isbn(epub_path):
    print("extracting isbn: \033[94m" + os.path.basename(epub_path) + "\033[0m")
    
    try:
        with zipfile.ZipFile(epub_path, 'r') as myzip:
            for file in myzip.namelist():
                if file.endswith('.opf'):
                    data = myzip.read(file).decode('utf-8')
                    soup = BeautifulSoup(data, 'xml')
                    isbn_node = soup.find('dc:identifier', attrs={'opf:scheme': 'ISBN'})
                    if isbn_node:
                        isbn = isbn_node.text

                        # Remove 'urn:isbn:' from the ISBN if it's there
                        if isbn.startswith('urn:isbn:'):
                            isbn = isbn[9:]

                        print("\t- found: \033[96m" + str(isbn) + "\033[0m")

                        return isbn
                    
                    else: 
                        print("\033[91m\t- no isbn found\033[0m")
                        title_node = soup.find('dc:title')
                        if title_node:
                            title = title_node.text
                            print("\t- trying to find isbn by title: \033[96m" + title + "\033[0m")
                            isbn = get_isbn_from_title(title, GOOGLE_BOOKS_API_KEY)
                            if isbn:
                                print("\t- found: \033[96m" + str(isbn) + "\033[0m")
                                return isbn
                            else:
                                print("\033[91m\t- no isbn found for title\033[0m")

    except FileNotFoundError:
        print("\033[91m\t- File not found: \033[0m" + epub_path)

    print("_____________________________________________\n")

    return None



# searching for isbn by title on google books api
def get_isbn_from_title(title, api_key):
    response = requests.get(f'https://www.googleapis.com/books/v1/volumes?q={title}&key={api_key}')
    data = json.loads(response.text)
    if 'items' in data:
        for item in data['items']:
            if 'industryIdentifiers' in item['volumeInfo']:
                for identifier in item['volumeInfo']['industryIdentifiers']:
                    if identifier['type'] == 'ISBN_13':
                        return identifier['identifier']
    return None



# downloading cover and saving it to the output_path
def download_cover(isbn, output_path):
    # Check if the file already exists
    if os.path.isfile(output_path):
        print("\033[93m\t- cover already exists, skipping download\033[0m")
        return

    url = f'https://buch.isbn.de/gross/{isbn}.jpg'
    response = requests.get(url)

    print("\t- downloading from url: \033[96m" + url + "\033[0m")
    
    md5_hash = hashlib.md5()
    md5_hash.update(response.content)
    if md5_hash.hexdigest() == 'f81b2d84d8a69ba9e8bf1f50c806faab':
        print("\033[93m\t- generic cover image detected, skipping\033[0m")
        return

    with open(output_path, 'wb') as out_file:
        out_file.write(response.content)

        print("\033[1;92m\t- done! cover saved to: " + output_path + "\033[0m")



# searching recursively over a directory and its subdirectories for epub files and calling extract_isbn and download_cover on them
def search_directory(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.epub'):
                epub_path = os.path.join(root, file)
                isbn = extract_isbn(epub_path)
                if isbn:

                    print("\t- get cover for isbn: \033[96m" + str(isbn) + "\033[0m")

                    cover_path = os.path.join(root, 'cover.jpg')
                    download_cover(isbn, cover_path)

                    print("_____________________________________________\n")

if len(sys.argv) != 2:
    print("Usage: python getBookCovers.py <path to folder>")
    sys.exit(1)

search_directory(sys.argv[1])