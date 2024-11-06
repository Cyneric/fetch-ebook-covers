# Book Cover Downloader

A Python script that recursively searches through directories to find EPUB files, extracts their ISBNs, and downloads corresponding book covers.

## Features

- Recursive directory scanning for EPUB files
- ISBN extraction from EPUB metadata
- Fallback to title-based ISBN lookup if no ISBN found
- Multiple cover sources:
  - buch.isbn.de
  - OpenLibrary
  - Google Books API
- Generic cover detection and filtering
- Colorized console output

## Prerequisites
```bash
pip install beautifulsoup4 requests lxml
```

## Usage
```bash
python getBookCovers.py <path_to_folder>
```

## Configuration

You can optionally set a Google Books API key in the script:
```python
GOOGLE_BOOKS_API_KEY = "your_api_key_here"
```

## How it works

1. Scans the given directory and subdirectories for .epub files
2. For each EPUB file:
   - Extracts ISBN from metadata
   - If no ISBN found, attempts to find ISBN using book title and author
   - Downloads cover from multiple sources
   - Saves cover as "cover.jpg" in the same directory as the EPUB

## Authors

- Original Author: Christian Blank <christianblank91@gmail.com>

## License

MIT License

Copyright (c) 2024 Christian Blank

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.