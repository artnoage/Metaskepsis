import gradio as gr
import os
import shutil
import pypdf
import markdown

# "Call" methods
def create_project(name):
    if not name or not name.strip():
        return "Project name cannot be empty.", None
    if not name.isalnum():
        return "Project name must contain only letters and numbers.", None
    project_path = os.path.join("projects", name)
    if os.path.exists(project_path):
        return f"Project '{name}' already exists.", None
    os.makedirs(os.path.join(project_path, "main"))
    os.makedirs(os.path.join(project_path, "temp"))
    return f"Project '{name}' created successfully.", name

def get_projects():
    if not os.path.exists("projects"):
        os.makedirs("projects")
    projects = []
    for d in os.listdir("projects"):
        project_path = os.path.join("projects", d)
        if os.path.isdir(project_path):
            try:
                mod_time = max(
                    os.path.getmtime(os.path.join(root, file))
                    for root, _, files in os.walk(project_path)
                    for file in files
                )
            except ValueError:  # This will catch the empty sequence error
                mod_time = os.path.getmtime(project_path)
            projects.append((d, mod_time))
    projects.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in projects]

def get_project_files(project):
    if not project:
        return []
    main_files = [os.path.join("main", f) for f in os.listdir(os.path.join("projects", project, "main"))]
    temp_files = [os.path.join("temp", f) for f in os.listdir(os.path.join("projects", project, "temp"))]
    return main_files + temp_files

def preview_file(project, file_path):
    if not project or not file_path:
        return "No file selected."
    full_path = os.path.join("projects", project, file_path)
    if not os.path.exists(full_path):
        return "File not found."
    
    if file_path.lower().endswith('.pdf'):
        with open(full_path, 'rb') as f:
            pdf = pypdf.PdfReader(f)
            text = ""
            for page in pdf.pages:
                text += page.extract_text() + "\n\n"
        return text
    elif file_path.lower().endswith('.md'):
        with open(full_path, 'r') as f:
            content = f.read()
        return markdown.markdown(content)
    else:
        with open(full_path, 'r') as f:
            return f.read()

def upload_file(project, file):
    if not project:
        return "No project selected.", None
    if not file:
        return "No file uploaded.", None
    filename = file.name
    target_path = os.path.join("projects", project, "temp", filename)
    shutil.copy(file.name, target_path)
    return f"File '{filename}' uploaded successfully.", get_project_files(project)

# Handler methods
def toggle_project_actions(choice):
    if choice == "Create Project":
        return gr.update(visible=True), gr.update(visible=False)
    else:
        return gr.update(visible=False), gr.update(visible=True)

def on_create_project(name, creation_method):
    if creation_method == "empty":
        result, project = create_project(name)
    elif creation_method == "pilot":
        result = "Creating project with pilot file is not implemented yet."
        project = None
    elif creation_method == "llm":
        result = "Creating project with LLM is not implemented yet."
        project = None
    else:
        result = "Invalid creation method."
        project = None

    projects = get_projects()
    if project:
        return result, project, projects, get_project_files(project), "Choose Project", gr.update(choices=projects)
    return result, "", projects, [], "Create Project", gr.update(choices=projects)

def on_project_select(project):
    return project, get_project_files(project)

def on_file_select(project, files):
    return files

def on_chat_send(project, message, history):
    history.append((message, f"[Placeholder] Response for: {message}"))
    return "", history

# Gradio interface


with gr.Blocks(theme='gstaff/sketch') as app:
    current_project = gr.State("")
    selected_files = gr.State([])
    new_project_name = gr.State("")
    chat_input = gr.State("")
    chat_history = gr.State([])

    with gr.Tab("Project Management"):
        project_action = gr.Radio(["Create Project", "Choose Project"], label="Action", value="Create Project")
        
        with gr.Group() as create_project_group:
            new_project_input = gr.Textbox(label="New Project Name")
            with gr.Row():
                create_empty_project_btn = gr.Button("Create Empty Project")
                create_pilot_project_btn = gr.Button("Create Project with Pilot File (Placeholder)")
                create_llm_project_btn = gr.Button("Create Project with LLM (Placeholder)")
            create_project_output = gr.Textbox(label="Output")

        with gr.Group(visible=False) as choose_project_group:
            project_dropdown = gr.Dropdown(choices=get_projects(), label="Choose Project", interactive=True)

    with gr.Tab("Project Workspace"):
        with gr.Row(variant="panel",elem_classes="workspace-container"):
            with gr.Column(scale=1):
                file_list = gr.Dropdown(multiselect=True, label="Files", interactive=True)
                upload_button = gr.UploadButton("Upload File", file_types=["text", "pdf", "md"])

            with gr.Column(scale=2):
                chat_output = gr.Chatbot(label="Chat")
                chat_input = gr.Textbox(label="Chat Input")
                chat_button = gr.Button("Send")
            with gr.Column(scale=1):
                preview_button = gr.Button("Preview Selected File")
                file_preview = gr.Markdown(label="File Preview")

    # Add custom CSS to make the workspace container scrollable
    

# Apply the custom CSS to the entire Gradio app


    # Event connections
    project_action.change(
        toggle_project_actions,
        inputs=[project_action],
        outputs=[create_project_group, choose_project_group]
    )

    create_empty_project_btn.click(
        lambda name: on_create_project(name, "empty"),
        inputs=[new_project_input],
        outputs=[create_project_output, current_project, project_dropdown, file_list, project_action, project_dropdown]
    )

    create_pilot_project_btn.click(
        lambda name: on_create_project(name, "pilot"),
        inputs=[new_project_input],
        outputs=[create_project_output, current_project, project_dropdown, file_list, project_action, project_dropdown]
    )

    create_llm_project_btn.click(
        lambda name: on_create_project(name, "llm"),
        inputs=[new_project_input],
        outputs=[create_project_output, current_project, project_dropdown, file_list, project_action, project_dropdown]
    )

    project_dropdown.change(
        on_project_select,
        inputs=[project_dropdown],
        outputs=[current_project, file_list]
    )

    file_list.change(
        on_file_select,
        inputs=[current_project, file_list],
        outputs=[selected_files]
    )

    preview_button.click(
        preview_file,
        inputs=[current_project, selected_files],
        outputs=[file_preview]
    )

    chat_button.click(
        on_chat_send,
        inputs=[current_project, chat_input, chat_history],
        outputs=[chat_input, chat_output]
    )

    upload_button.upload(
        upload_file,
        inputs=[current_project, upload_button],
        outputs=[create_project_output, file_list]
    )

    # Initialize with the most recent project or default to "Create Project"
    initial_projects = get_projects()
    if initial_projects:
        app.load(lambda: (initial_projects[0], get_project_files(initial_projects[0]), "Choose Project"), 
                 outputs=[current_project, file_list, project_action])
    else:
        app.load(lambda: "Create Project", outputs=[project_action])

app.launch()