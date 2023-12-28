Author: Christian Blank <git@cyneric.de>

License: Open Source (GPL3)

python script to run recursively over a folder and its subfolders to extract isbns from epub files and download book cover and place them besides the epub files named as cover.jpg

dependencies: BeautifulSoup, requests, lxml (pip install them if you don't have them already)
to install dependencies run: "pip install beautifulsoup4 requests lxml" (or pip3 if you are using python3)

Usage: python getBookCovers.py /path/to/folder
