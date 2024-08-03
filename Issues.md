# Issues with Current LangChain Academic Task Automation Bot

## 1. ChatGoogle Tool Calling Integration
- The retriever agent, which uses ChatGoogle, is not properly handling tool calling.
- The code currently looks for tool calling in additional keywords, but needs to be adjusted to look elsewhere in ChatGoogle's response.
- No changes are required in the bind tool function itself.

## 2. Replacement of arXiv with Semantic Scholar
- Complete replacement of arXiv with Semantic Scholar is planned.
- Semantic Scholar will also replace Google Scholar functionality.
- Benefits include:
  - Better match finding
  - Improved filtering for papers with available PDFs
  - More comprehensive source coverage

## 3. PDF to Markdown Conversion Improvement
- Current method uses nougat for local conversion.
- Proposed new approach:
  - Convert PDF pages to images
  - Use Gemini API to transcribe content from each image
  - Process one image per API request
  - Implement parallel API calls to reduce processing time
- Considerations:
  - Average PDF length: 30-40 pages
  - Gemini performs suboptimally with >10,000 characters
  - Web app should remain lightweight (no additional OCR/document processing APIs)

## 4. Enhanced Citation Workflow
- Two-pass system:
  1. First pass: Locate all citations (last page and throughout for CS papers)
  2. Second pass: Apply complex criteria to filter citations
- Complex criteria examples:
  - Citations where the work is mentioned in more than two lines
  - Citations where the cited technique is explained before the reference
- Current workflow:
  - Identifies full bibliography
  - Uses bibliography as context to find citations meeting criteria
- Challenge: Handling split text (potentially page by page)

## 5. Improved RAG (Retrieval-Augmented Generation) Workflow
- Implement a temporary folder system for information storage
- Store all necessary info for effective retrieval
- When user asks a question, provide:
  - Relevant citation
  - Source paper
  - Specific page number
- Ensure users only see their own files, not the entire database
