# @Author: Christian Blank <git@cyneric.de>
# @License: Open Source (GPL3)

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
import re



GOOGLE_BOOKS_API_KEY = ""; # your google books api key here



# extracting isbn from .opf file inside the epub file
def extract_isbn(epub_path):
    print("\t- extracting isbn fom .epub container")
    
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


                            # Extract the author from the file path and Extract the year from the directory name
                            author = os.path.dirname(epub_path).split(os.path.sep)[2]
                            match = re.search(r'\((.*?)\)', os.path.dirname(epub_path))
                            year = match.group(1) if match else None

                            isbn = get_isbn_from_title(author, title, year, GOOGLE_BOOKS_API_KEY)
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
def get_isbn_from_title(author, title, year, api_key):
    query = f'https://www.googleapis.com/books/v1/volumes?q={title}'
    if  author:
        query += f' {author}'
        # query += f'+inauthor:{author}'
    if year:
        query += f' ({year})'
        # query += f'+inpublisher:{year}'

    if api_key:
        query += f'&key={api_key}'
    

    print("\t- request: \033[96m" + query + "\033[0m") # debug!
    response = requests.get(query)    
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

    # try downloading from buch.isbn.de  
    url = f'https://buch.isbn.de/gross/{isbn}.jpg'
    response = requests.get(url)

    print("\t- downloading from url: \033[96m" + url + "\033[0m")
    
    md5_hash = hashlib.md5()
    md5_hash.update(response.content)
    if md5_hash.hexdigest() == 'f81b2d84d8a69ba9e8bf1f50c806faab':
        print("\033[93m\t- generic cover image detected, skipping\033[0m")
        
         # Alternatively try downloading from openlibrary.org
        url = f'http://covers.openlibrary.org/b/isbn/{isbn}-L.jpg'
        response = requests.get(url)
        
        print("\t- trying alternative source: \033[96m" + url + "\033[0m")

        md5_hash = hashlib.md5()
        md5_hash.update(response.content)
        if md5_hash.hexdigest() == '0d23d0b62908b75e89014ac3f864484e':
            print("\033[93m\t- generic cover image detected, skipping\033[0m")
            
            
            # Try downloading from Google Books API
            url = f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}'
            response = requests.get(url)

            print("\t- trying alternative source: \033[96m" + url + "\033[0m")

            response_data = response.json()

            if 'items' in response_data:
                image_links = response_data['items'][0]['volumeInfo'].get('imageLinks', {})
                if 'thumbnail' in image_links:
                    image_url = image_links['thumbnail']
                    response = requests.get(image_url)

                else:
                    print("\033[91m\t- no cover found\033[0m")
                    return
            else:
                print("\033[91m\t- no cover found\033[0m")
                return

        if response.status_code != 200:
            print("\033[91m\t- no cover found\033[0m")
            return

    with open(output_path, 'wb') as out_file:
        out_file.write(response.content)

        print("\033[1;92m\t- done! cover saved to: " + output_path + "\033[0m")



# searching recursively over a directory and its subdirectories for epub files and calling extract_isbn and download_cover on them
def search_directory(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            cover_path = os.path.join(root, 'cover.jpg')

            if file.endswith('.epub'):
                epub_path = os.path.join(root, file)

                print("\033[94m Started processing file: " + os.path.basename(epub_path) + "\033[0m")


                # Check if the file already exists and skip it if it does
                if os.path.isfile(cover_path):
                    print("\033[93m\t- cover already exists, skipping download\033[0m")
                    print("_____________________________________________\n")

                    continue

                isbn = extract_isbn(epub_path)
                if isbn:

                    print("\t- get cover for isbn: \033[96m" + str(isbn) + "\033[0m")
                    download_cover(isbn, cover_path)

                    print("_____________________________________________\n")

if len(sys.argv) != 2:
    print("Usage: python getBookCovers.py <path to folder>")
    sys.exit(1)

search_directory(sys.argv[1])