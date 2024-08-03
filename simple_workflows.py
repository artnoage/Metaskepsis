from langgraph.graph import END, StateGraph
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage
from langgraph.prebuilt import ToolInvocation
from langgraph.prebuilt.tool_executor import ToolExecutor
from typing import TypedDict, Annotated
from langchain_google_genai import ChatGoogleGenerativeAI
import operator
from tqdm import tqdm
from prompts import *
from simple_tools import *
from langchain_text_splitters import CharacterTextSplitter
import os
import fitz
import io
import base64
import concurrent.futures
import time
import latex2markdown
from PIL import Image
class ArxivState(TypedDict):
    receptionist_retriever_history: Annotated[list[BaseMessage], operator.add]
    last_action_outcome: Annotated[list[BaseMessage], operator.add]
    metadata: BaseMessage
    article_keywords: BaseMessage
    title_of_retrieved_paper: BaseMessage
    should_I_clean: bool
    history_reset_counter: int


class OcrState(TypedDict):
    main_text_filename: BaseMessage
    report: BaseMessage

class KeywordSummaryState(TypedDict):
    main_text_filename: BaseMessage
    report: BaseMessage


class TranslatorState(TypedDict):
    auxilary_text_filename: BaseMessage
    target_language: BaseMessage
    main_text_filename: BaseMessage
    report: BaseMessage


class CitationExtractorState(TypedDict):
    main_text_filename: BaseMessage
    extraction_type: BaseMessage
    auxilary_text_filename: BaseMessage
    report: BaseMessage


class TakeAPeakState(TypedDict):
    main_text_filename: BaseMessage
    report: BaseMessage


class CreatorState(TypedDict):
    creator_history: Annotated[list[BaseMessage], operator.add]
    backsandforths: int

class CreatorWorkflow:
    def __init__(self, key, creator_model=None, inquirer_model=None):
        if creator_model == None:
            self.creator_model = ChatGoogleGenerativeAI(google_api_key=key,model="gemini-1.5-flash",temperature=0)
        else:
            self.creator_model = creator_model
        if inquirer_model == None:
            self.inquirer_model = ChatGoogleGenerativeAI(google_api_key=key,model="gemini-1.5-flash",temperature=0)
        else:
            self.inquirer_model = inquirer_model

        self.creator = creator_prompt_template | self.creator_model
        self.inquirer = inquirer_prompt_template | self.inquirer_model
        

    def supervisor_run(self, state):
        action = self.supervisor.invoke(state)
        print(action.content)
        return {"manager_history": [action]}

    def call_tool(self, state):
        last_message = state["manager_history"][-1]
        tool_call = last_message.tool_calls[0]
        action = ToolInvocation(tool=tool_call["name"], tool_input=tool_call["args"])
        try:
            response = self.tool_executor.invoke(action)
        except Exception as e:
            response = str(e)
        print(response)
        response = ToolMessage(content=response, tool_call_id=tool_call["id"])
        return {"manager_history": [response]}

    def user_run(self, state):
        action = HumanMessage(content=input("Enter your answer/querry: "))
        print(action)
        return {"manager_history": [action]}

    def where_next_supervisor(self, state):
        if "tool_calls" in state["manager_history"][-1].additional_kwargs:
            return "tools"
        else:
            return "user"

    def where_next_user(self, state):
        if "exit" in state["manager_history"][-1].content:
            return "end"
        else:
            return "supervisor"

    def create_workflow(self):
        workflow = StateGraph(MetaState)
        workflow.set_entry_point("creator")
        workflow.add_node("supervisor", self.supervisor_run)
        workflow.add_node("tools", self.call_tool)
        workflow.add_node("user", self.user_run)
        workflow.add_edge("tools", "supervisor")
        workflow.add_conditional_edges(
            "supervisor", self.where_next_supervisor, {"tools": "tools", "user": "user"}
        )
        workflow.add_conditional_edges(
            "user", self.where_next_user, {"end": END, "supervisor": "supervisor"}
        )
        workflow.add_edge("tools", "user")
        return workflow


model = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
workflow = MetaWorkflow(model)
app = workflow.create_workflow()
app = app.compile()
app.invoke(
    {
        "manager_history": [HumanMessage(content="How can I help you today")],
        "folder_structure": get_folder_structure(),
    }
)




class ArxivRetrievalWorkflow:
    def __init__(
        self, retriever_model=None, cleaner_model=None, receptionist_model=None
    ):
        if retriever_model == None:
            self.retriever_model = ChatGoogleGenerativeAI(model="gemini-1.5-flash",temperature=0)
        else:
            self.retriever_model = retriever_model

        if cleaner_model == None:
            self.cleaner_model =  ChatGoogleGenerativeAI(model="gemini-1.5-flash",temperature=0)
        else:
            self.cleaner_model = cleaner_model
        if receptionist_model == None:
            self.receptionist_model =  ChatGoogleGenerativeAI(model="gemini-1.5-flash",temperature=0)
        else:
            self.receptionist_model = receptionist_model

        self.tools = [get_id_from_url, download_pdf]
        self.retriever = (
            arxiv_retriever_prompt_template
            | self.retriever_model.bind_tools(self.tools)
        )
        self.cleaner = arxiv_metadata_scraper_prompt_template | self.cleaner_model
        self.receptionist = arxiv_receptionist_prompt_template | self.receptionist_model
        self.tool_executor = ToolExecutor(self.tools)

    def run_receptionist(self, state):
        action = self.receptionist.invoke(state)
        if "We are done" in action.content:
            print("Receptionist:" + action.content)
        else:
            print(
                "Receptionist: The following has been forwarded to the arxiv_retriever: ",
                action.content,
            )
        return {
            "receptionist_retriever_history": [action],
            "article_keywords": action.content,
            "last_action_outcome": ["No action was taken"],
            "history_reset_counter": len(state["last_action_outcome"]),
        }

    def run_retriever(self, state):
        state["last_action_outcome"] = state["last_action_outcome"][
            state["history_reset_counter"] :
        ]
        action = self.retriever.invoke(state)

        if "tool_calls" in action.additional_kwargs:
            pr = "Retriever: I am going to call  " + action.tool_calls[0]["name"]
            print(pr)
            return {"last_action_outcome": [action]}
        else:
            pr = (
                "Retriever:I am reporting back to the arxiv_receptionist with"
                + action.content
            )
            print(pr)
            return {
                "receptionist_retriever_history": [action],
                "last_action_outcome": [action],
            }

    def run_cleaner(self, state):
        action = self.cleaner.invoke(state)
        if "error" in action.content:
            pr = "Scraper: I got an error, going back to the arxiv_retriever"
            print(pr)
            return {"last_action_outcome": [action], "should_I_clean": True}
        else:
            pr = "Scraper: I got the following paper" + action.content
            print(pr)
            return {
                "title_of_retrieved_paper": action.content,
                "last_action_outcome": [action],
                "should_I_clean": False,
            }

    def call_tool(self, state):
        last_message = state["last_action_outcome"][-1]
        tool_call = last_message.tool_calls[0]
        action = ToolInvocation(tool=tool_call["name"], tool_input=tool_call["args"])
        try:
            response = self.tool_executor.invoke(action)
        except Exception as e:
            response = str(e)
        report = ToolMessage("The tool was called", tool_call_id=tool_call["id"])
        response = ToolMessage(response, tool_call_id=tool_call["id"])
        if tool_call["name"] == "get_id_from_url":
            pr = (
                "Tool_executor: I am going to execute"
                + str(tool_call["name"])
                + "with"
                + str(tool_call["args"])
            )
            print(pr)
            return {
                "last_action_outcome": [report],
                "metadata": response,
                "should_I_clean": True,
            }
        elif tool_call["name"] == "download_pdf":
            pr = (
                "Tool_executor: I am going to execute"
                + str(tool_call["name"])
                + "with"
                + str(tool_call["args"])
            )
            print(pr)
            return {"last_action_outcome": [response]}

    def should_continue_receptionist(self, state):
        messages = state["receptionist_retriever_history"]
        last_message = messages[-1]
        # If there is no function call, then we finish
        if "We are done" in str(last_message.content):
            return "end"
        else:
            return "continue"

    def should_continue_retriever(self, state):
        message = state["last_action_outcome"][-1]

        # If there is no function call, then we finish
        if "tool_calls" in message.additional_kwargs:
            return "continue"
        # Otherwise if there is, we continue
        else:
            print("Reporting to receptionist")
            return "receptionist"

    def where_next(self, state):
        if state["should_I_clean"] == True:
            return "cleaner"
        # Otherwise if there is, we continue
        else:
            return "retriever"

    def create_workflow(self):
        workflow = StateGraph(ArxivState)
        workflow.set_entry_point("receptionist")
        workflow.add_node("receptionist", self.run_receptionist)
        workflow.add_conditional_edges(
            "receptionist",
            self.should_continue_receptionist,
            {"end": END, "continue": "retriever"},
        )
        workflow.add_node("retriever", self.run_retriever)
        workflow.add_conditional_edges(
            "retriever",
            self.should_continue_retriever,
            {
                "continue": "tools",
                "receptionist": "receptionist",
            },
        )
        workflow.add_node("tools", self.call_tool)
        workflow.add_node("cleaner", self.run_cleaner)
        workflow.add_conditional_edges(
            "tools",
            self.where_next,
            {
                "cleaner": "cleaner",
                "retriever": "retriever",
            },
        )
        workflow.add_edge("cleaner", "retriever")
        return workflow


class KeywordAndSummaryWorkflow:
    def __init__(self, keyword_and_summary_maker_model=None):
        if keyword_and_summary_maker_model == None:
            self.keyword_and_summary_maker_model =  ChatGoogleGenerativeAI(model="gemini-1.5-flash",temperature=0)
        else:
            self.keyword_and_summary_maker_model = keyword_and_summary_maker_model
        self.keyword_and_summary_maker = (
            keyword_and_summary_maker_template | self.keyword_and_summary_maker_model
        )

    def run_keyword_and_summary_maker(self, state):
        text_name = state["main_text_filename"].content
        text_name = get_filename_without_extension(text_name)
        with open(f"files/markdowns/{text_name}.mmd", "r", encoding="utf-8") as f:
            text = f.read()

        text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=0)
        text = text_splitter.split_text(text)
        keyword_and_summary = ""
        print("keyword_and_summary in progress")
        for i in tqdm(range(len(text))):
            keyword_and_summary = self.keyword_and_summary_maker.invoke(
                {"text": keyword_and_summary, "page": text[i]}
            ).content

        output_filename = f"files/markdowns/{text_name}_keyword_and_summary.mmd"
        with open(output_filename, "w", encoding="utf-8") as file:
            file.write(keyword_and_summary)

        report = f"keyword_and_summary completed successfully and the resulted file is named {text_name}_keyword_and_summary"
        print(report)
        return {"report": HumanMessage(content=report)}

    def create_workflow(self):
        """
        Create a workflow that executes the keyword and summary extraction.
        """
        workflow = StateGraph(KeywordSummaryState)
        workflow.set_entry_point("summarizer")
        workflow.add_node("summarizer", self.run_keyword_and_summary_maker)
        workflow.add_edge("summarizer", END)
        return workflow
    
class OcrWorkflow:
    def __init__(self, ocr_model=None):
        if ocr_model == None:
            self.ocr_model =  ChatGoogleGenerativeAI(model="gemini-1.5-flash",temperature=0)
        else:
            self.ocr_model = ocr_model
        self.ocr = (ocr_prompt_template | self.ocr_model)

    def run_ocr(self, state):
        
        # Ensure Pandoc is available
        #pypandoc.download_pandoc()
        text_name = state["main_text_filename"].content
        text_name = get_filename_without_extension(text_name)
        # Path to the PDF file
        # Convert PDF to images
        pdf_document = fitz.open("files\\pdfs\\"+text_name+".pdf")

        # List to store images
        images = []


        # Iterate over PDF pages
        for page_number in range(len(pdf_document)):
        # Get the page
            page = pdf_document.load_page(page_number)
    
        # Convert the page to a pixmap (image) with the zoom factor
            pix = page.get_pixmap()
    
        # Convert the pixmap to an image (Pillow Image)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
        # Save the image to a BytesIO object in JPEG format
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            #file_name = f"page_{page_number + 1}.jpg"
            #file_path = os.path.join(os.getcwd(), file_name)
            #image.save(file_path, format="JPEG")

        # Encode the image to base64
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        # Iterate over PDF pages
            images.append(img_str)


        ocr = ""
        print("ocr in progress")

        def process_image(index, image):
            return index, self.ocr.invoke({"image_data": image}).content

        def process_batch(batch_with_indices):
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_image, idx, image) for idx, image in batch_with_indices]
                results = [None] * len(batch_with_indices)
                for future in concurrent.futures.as_completed(futures):
                    idx, result = future.result()
                    results[idx % 5] = result
            return results

        batch_size = 5
        ocr = []

        for i in tqdm(range(0, len(images), batch_size)):
            time0=time.time()
            batch = images[i:i+batch_size]
            batch_with_indices = list(enumerate(batch, start=i))
            batch_results = process_batch(batch_with_indices)
            times=time.time()-time0
            if times<20 and (len(images)-i)>batch_size:
                time.sleep(20-times)
            ocr.extend(batch_results)
        # Remove any None values that might have been added for incomplete batches
        ocr = [result for result in ocr if result is not None]
        # Join all the OCR results into a single string
        ocr_text = "".join(ocr)
        output_mmd = f"files/markdowns/{text_name}_ocr.mmd"

        with open(output_mmd,"w",encoding="utf-8",) as f:
            f.write(ocr_text)
        report = f"keyword_and_summary completed successfully and the resulted file is named {text_name}_keyword_and_summary"
        print(report)
        return {"report": HumanMessage(content=report)}
        
    def create_workflow(self):
        """
        Create a workflow that executes the keyword and summary extraction.
        """
        workflow = StateGraph(OcrState)
        workflow.set_entry_point("ocr_runner")
        workflow.add_node("ocr_runner", self.run_ocr)
        workflow.add_edge("ocr_runner", END)
        return workflow


class TranslationWorkflow:
    def __init__(self, translator_model=None):
        if translator_model == None:
            self.translator_model = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
        else:
            self.translator_model = translator_model
        self.translator = translator_prompt_template | self.translator_model

    def run_translator(self, state):
        auxilary_text_filename = state["auxilary_text_filename"].content
        target_language = state["target_language"].content
        main_text_filename = state["main_text_filename"].content
        main_text_filename = get_filename_without_extension(main_text_filename)
        auxilary_text_filename = get_filename_without_extension(auxilary_text_filename)

        text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=0)
        with open(
            f"files/markdowns/{main_text_filename}.mmd", "r", encoding="utf-8"
        ) as f:
            text = f.read()
        try:
            with open(
                f"files/markdowns/{auxilary_text_filename}.mmd", "r", encoding="utf-8"
            ) as f:
                auxilary_text = f.read()
        except FileNotFoundError:
            print(
                "File not found: The auxilary_text file does not exist. Assuming auxilary_text is blank."
            )
            auxilary_text = " "

        if "_without_proofs" in main_text_filename:
            main_text_filename = main_text_filename.replace("_without_proofs", "")

        listed_text = text_splitter.split_text(text)
        translation = ""

        print(f"Translation of {main_text_filename} in progress")

        for i in tqdm(range(len(listed_text))):
            translation = (
                translation
                + self.translator.invoke(
                    {
                        "language": target_language,
                        "auxilary_text": auxilary_text,
                        "page": listed_text[i],
                    }
                ).content
            )

        with open(
            f"files/markdowns/{main_text_filename}_{target_language}.mmd",
            "w",
            encoding="utf-8",
        ) as f:
            f.write(translation)

        return {"report": HumanMessage(content="Translation completed")}

    def create_workflow(self):
        workflow = StateGraph(TranslatorState)
        workflow.set_entry_point("translator")
        workflow.add_node("translator", self.run_translator)
        workflow.add_edge("translator", END)
        return workflow


class CitationExtractionWorkflow:
    def __init__(
        self,
        citation_extractor_model=None,
        citation_retriever_model=None,
        citation_cleaner_model=None,
    ):
        if citation_extractor_model == None:
            self.citation_extractor_model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash"
            )
        else:
            self.citation_extractor_model = citation_extractor_model
        if citation_retriever_model == None:
            self.citation_retriever_model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash"
            )
        else:
            self.citation_retriever_model = citation_retriever_model
        if citation_cleaner_model == None:
            self.citation_cleaner_model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash"
            )
        else:
            self.citation_cleaner_model = citation_cleaner_model

        self.citation_extractor = (
            citation_extractor_prompt_template | self.citation_extractor_model
        )
        self.citation_retriever = (
            citation_retriever_prompt_template | self.citation_retriever_model
        )
        self.citation_cleaner = (
            citation_cleaner_prompt_template | self.citation_cleaner_model
        )

    def run_citation_retriever(self, state):
        main_text_filename = state["main_text_filename"].content
        auxilary_text_filename = state["auxilary_text_filename"].content
        main_text_filename = get_filename_without_extension(main_text_filename)
        auxilary_text_filename = get_filename_without_extension(auxilary_text_filename)

        text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=0)
        with open(
            f"files/markdowns/{main_text_filename}.mmd", "r", encoding="utf-8"
        ) as f:
            text = f.read()

        listed_text = text_splitter.split_text(text)
        citations = ""

        print(
            f"Retriving full list of  citations from {main_text_filename} in progress"
        )

        for i in tqdm(range(len(listed_text))):
            citations = (
                citations
                + self.citation_retriever.invoke(
                    {"main_text": HumanMessage(content=listed_text[i])}
                ).content
            )
        return {"report": HumanMessage(content=citations)}

    def run_citation_extractor(self, state):
        main_text_filename = state["main_text_filename"].content
        extraction_type = state["extraction_type"].content
        auxilary_text_filename = state["auxilary_text_filename"].content
        list_of_citations = state["report"].content
        main_text_filename = get_filename_without_extension(main_text_filename)
        auxilary_text_filename = get_filename_without_extension(auxilary_text_filename)

        text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=0)
        with open(
            f"files/markdowns/{main_text_filename}.mmd", "r", encoding="utf-8"
        ) as f:
            text = f.read()

        try:
            with open(
                f"files/markdowns/{auxilary_text_filename}.mmd", "r", encoding="utf-8"
            ) as f:
                auxilary_text = f.read()
        except FileNotFoundError:
            print(
                "File not found: Auxilary file not provided or wrong filename. I proceed without context."
            )
            auxilary_text = "No"

        listed_text = text_splitter.split_text(text)
        citations = ""

        print(
            f"Extracting requested type of citations from {main_text_filename} in progress"
        )

        for i in tqdm(range(len(listed_text))):
            citations = (
                citations
                + self.citation_extractor.invoke(
                    {
                        "extraction_type": extraction_type,
                        "main_text": listed_text[i],
                        "auxiliary_text": auxilary_text,
                        "list_of_citations": list_of_citations,
                    }
                ).content
            )

        return {"report": HumanMessage(content=list_of_citations)}

    def run_citation_cleaner(self, state):
        citations = state["report"].content
        main_text_filename = state["main_text_filename"].content
        citations = self.citation_cleaner.invoke(
            {"list_of_citations": citations}
        ).content
        with open(
            f"files/markdowns/{main_text_filename}_citations.mmd", "w", encoding="utf-8"
        ) as f:
            f.write(citations)
        return {"report": HumanMessage(content="Citations have been saved.")}

    def create_workflow(self):
        workflow = StateGraph(CitationExtractorState)
        workflow.set_entry_point("citation_retriever")
        workflow.add_node("citation_retriever", self.run_citation_retriever)
        workflow.add_node("citation_extractor", self.run_citation_extractor)
        workflow.add_node("citation_cleaner", self.run_citation_cleaner)
        workflow.add_edge("citation_retriever", "citation_extractor")
        workflow.add_edge("citation_extractor", "citation_cleaner")
        workflow.add_edge("citation_cleaner", END)
        return workflow


class TakeAPeakWorkflow:
    def __init__(self, take_a_peak_model=None):
        if take_a_peak_model == None:
            self.take_a_peak_model = ChatGoogleGenerativeAI(model="gemini-1.5-flash")
        else:
            self.take_a_peak_model = take_a_peak_model
        self.take_a_peaker = keyword_and_summary_maker_template | self.take_a_peak_model

    def run_take_a_peaker(self, state):
        text_filename = state["main_text_filename"].content
        text_filename = get_filename_without_extension(text_filename)
        markdown_path1 = os.path.join(r"files\markdowns", f"{text_filename}.mmd")
        markdown_path2 = os.path.join(r"files\markdowns", f"{text_filename}.md")
        pdf_path = os.path.join(r"files\pdfs", f"{text_filename}.pdf")
        mupdf_path = os.path.join(r"files\temps", f"{text_filename}_temp.mmd")
        if os.path.exists(markdown_path1):
            with open(
                f"files/markdowns/{text_filename}.mmd", "r", encoding="utf-8"
            ) as f:
                text = f.read()
        elif os.path.exists(markdown_path2):
            with open(
                f"files/markdowns/{text_filename}.md", "r", encoding="utf-8"
            ) as f:
                text = f.read()
        elif os.path.exists(pdf_path):
            md_text = pymupdf4llm.to_markdown(pdf_path)
            pathlib.Path(mupdf_path).write_bytes(md_text.encode())
            with open(
                f"files/temps/{text_filename}_temp.mmd", "r", encoding="utf-8"
            ) as f:
                text = f.read()
        else:
            return {"report": "There was an error with the filename"}

        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
        text = text_splitter.split_text(text)
        peak = ""
        keyword_and_summary = ""
        if len(text) == 1:
            peak = "Here is the text:/n" + text[0]
        elif 4 > len(text) > 0:
            for i in tqdm(range(len(text))):
                keyword_and_summary = self.take_a_peaker.invoke(
                    {"text": keyword_and_summary, "page": text[i]}
                ).content
            peak = (
                "The text was too long here is the inital part of the text:/n"
                + text[0]
                + "/n And here is the summary:/n"
                + keyword_and_summary
            )
        else:
            for i in tqdm(range(3)):
                keyword_and_summary = self.take_a_peaker.invoke(
                    {"text": keyword_and_summary, "page": text[i]}
                ).content
            peak = (
                "The text was too long here is the inital part of the text:/n"
                + text[0]
                + "/n And here is the summary of the first three pages:"
                + keyword_and_summary
            )

        output_filename = f"files/temps/{text_filename}_takeapeak.mmd"
        with open(output_filename, "w", encoding="utf-8") as file:
            file.write(peak)

        if os.path.exists(mupdf_path):
            os.remove(mupdf_path)
            print(f"{mupdf_path} has been deleted.")
        else:
            print(f"{mupdf_path} does not exist.")
        return {"report": HumanMessage(content=peak)}

    def create_workflow(self):
        """
        Create a workflow that executes the keyword and summary extraction.
        """
        workflow = StateGraph(TakeAPeakState)
        workflow.set_entry_point("take_a_peaker")
        workflow.add_node("take_a_peaker", self.run_take_a_peaker)
        workflow.add_edge("take_a_peaker", END)
        return workflow
