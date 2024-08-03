import gradio as gr
import os
import shutil
import pypdf
import markdown
import re
import jwt
from datetime import datetime, timedelta
import secrets
import mimetypes
from simple_workflows import *
from simple_tools import *
from workflows_as_tools import *


# JWT configuration
JWT_SECRET = secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DELTA = timedelta(days=1)

# Helper functions
def generate_token(username):
    payload = {
        'username': username,
        'exp': datetime.utcnow() + JWT_EXPIRATION_DELTA
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def validate_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload['username']
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def is_valid_username(username):
    return bool(re.match(r'^[a-zA-Z0-9_]{3,20}$', username))

def get_user_folder(token):
    username = validate_token(token)
    return os.path.join("users", username) if username else None

def get_user_projects(token):
    user_folder = get_user_folder(token)
    if not user_folder or not os.path.exists(user_folder):
        return []
    projects = []
    for d in os.listdir(user_folder):
        project_path = os.path.join(user_folder, d)
        if os.path.isdir(project_path):
            try:
                mod_time = max(
                    os.path.getmtime(os.path.join(root, file))
                    for root, _, files in os.walk(project_path)
                    for file in files
                )
            except ValueError:
                mod_time = os.path.getmtime(project_path)
            projects.append((d, mod_time))
    projects.sort(key=lambda x: x[1], reverse=True)
    return [p[0] for p in projects]

def get_most_recent_project(token):
    projects = get_user_projects(token)
    return projects[0] if projects else None

# "Call" methods
def create_project(token, name):
    username = validate_token(token)
    if not username:
        return "Invalid token. Please log in again.", None
    if not name or not name.strip():
        return "Project name cannot be empty.", None
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return "Project name must contain only letters, numbers, underscores, and hyphens.", None
    project_path = os.path.join(get_user_folder(token), name)
    if os.path.exists(project_path):
        return f"Project '{name}' already exists.", None
    os.makedirs(os.path.join(project_path, "main"))
    os.makedirs(os.path.join(project_path, "temp"))
    return f"Project '{name}' created successfully.", name

def get_project_files(token, project):
    username = validate_token(token)
    if not username or not project:
        return []
    project_path = os.path.join(get_user_folder(token), project)
    if not os.path.exists(project_path):
        return []
    main_path = os.path.join(project_path, "main")
    temp_path = os.path.join(project_path, "temp")
    main_files = [os.path.join("main", f) for f in os.listdir(main_path)] if os.path.exists(main_path) else []
    temp_files = [os.path.join("temp", f) for f in os.listdir(temp_path)] if os.path.exists(temp_path) else []
    return main_files + temp_files

def preview_file(token, project, file_path):
    username = validate_token(token)
    if not username:
        return "Invalid token. Please log in again."
    if not project or not file_path:
        return "No file selected."
    full_path = os.path.join(get_user_folder(token), project, file_path)
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

def is_text_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type and mime_type.startswith('text/')

def is_pdf_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type == 'application/pdf'

def upload_file(token, project, file):
    username = validate_token(token)
    if not username:
        return "Invalid token. Please log in again.", None
    if not project:
        return "No project selected.", None
    if not file:
        return "No file uploaded.", None
    
    filename = file.name
    source_path = file.name
    
    if not (is_text_file(source_path) or is_pdf_file(source_path)):
        return "Only text-based files or PDFs are allowed.", None
    
    target_path = os.path.join(get_user_folder(token), project, "temp", os.path.basename(filename))
    
    try:
        shutil.copy2(source_path, target_path)
    except shutil.SameFileError:
        return f"File '{filename}' already exists in the project.", None
    except Exception as e:
        return f"Error uploading file: {str(e)}", None
    
    return f"File '{filename}' uploaded successfully.", get_project_files(token, project)

# Handler methods
def on_login(username):
    if not is_valid_username(username):
        return "Invalid username. Use 3-20 alphanumeric characters or underscores.", gr.update(visible=True), gr.update(visible=False), gr.update(visible=False), None, None, []
    
    user_folder = get_user_folder(generate_token(username))
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    
    token = generate_token(username)
    
    recent_project = get_most_recent_project(token)
    user_projects = get_user_projects(token)
    
    return f"Welcome, {username}!", gr.update(visible=False), gr.update(visible=True), gr.update(visible=True), token, recent_project, user_projects

def on_create_project(token, name, creation_method):
    username = validate_token(token)
    if not username:
        return "Invalid token. Please log in again.", "", [], [], gr.update(choices=[])
    
    if creation_method == "empty":
        result, project = create_project(token, name)
    elif creation_method == "pilot":
        result = "Creating project with pilot file is not implemented yet."
        project = None
    else:
        result = "Invalid creation method."
        project = None

    projects = get_user_projects(token)
    if project:
        return result, project, projects, get_project_files(token, project), gr.update(choices=projects)
    else:
        return result, "", projects, [], gr.update(choices=projects)

def on_project_select(token, project):
    username = validate_token(token)
    if not username:
        return "", []
    if isinstance(project, list) and project:
        project = project[0]
    return project, get_project_files(token, project)

def on_file_select(token, project, files):
    username = validate_token(token)
    if not username:
        return []
    return files

def on_chat_send_to_creator(token, message):
    username = validate_token(token)
    if not username:
        return "", "There is a validation error. Please log in again!"
    
    history.append((message, f"[Placeholder] Response for: {message}"))
    return "", history


def on_chat_send_to_manager(token, project, message):
    username = validate_token(token)
    if not username:
        return "", "There is a validation error. Please log in again!"
    history.append((message, f"[Placeholder] Response for: {message}"))
    return "", history

def update_project_dropdown(token):
    projects = get_user_projects(token)
    return gr.update(choices=projects)

# Gradio interface
with gr.Blocks(theme='gstaff/sketch') as app:
    token_state = gr.State("")
    current_project = gr.State("")
    selected_files = gr.State([])
    new_project_name = gr.State("")
    chat_input = gr.State("")
    chat_history = gr.State([])

    with gr.Column(elem_id="container"):
        with gr.Tab("Login") as login_tab:
            username_input = gr.Textbox(label="Username")
            login_button = gr.Button("Login")
            login_output = gr.Textbox(label="Login Status")

        with gr.Tab("Project Creation", visible=False) as project_creation_tab:
            new_project_input = gr.Textbox(label="New Project Name")
            with gr.Row():
                create_empty_project_btn = gr.Button("Create Empty Project")
                create_pilot_project_btn = gr.Button("Create Project with Pilot File")
            create_project_output = gr.Textbox(label="Output")
            
            gr.Markdown("### Project creator Chat")
            creator_chat_input = gr.Textbox(label="Chat with LLM")
            creator_chat_button = gr.Button("Send to creator")
            creator_chat_output = gr.Chatbot(
                label="Chat with the project creator",
                value=[
                    (None, """<p class="yellow-text">
                    Hello! I'm here to help you create your project. You have a few options:
                    1. Create an empty project where you can manually initiate your project.
                    2. Use a file as a pilot for your project. You give me a paper,and I get what your project is about.
                    3. Tell me about your project, and I'll help you set it up.
                    What would you like to do?
                    </p>""")
                ],
                elem_classes=["chatbot"]
            )
        with gr.Tab("Project Workspace", visible=False) as project_workspace_tab:
            with gr.Row(variant="panel"):
                with gr.Column(scale=1):
                    project_dropdown = gr.Dropdown(choices=[], label="Choose Project", interactive=True)
                    file_list = gr.Dropdown(multiselect=True, label="Files", interactive=True)
                    upload_button = gr.UploadButton("Upload File", file_types=["text", "pdf"])
                with gr.Column(scale=2):
                    manager_chat_output = gr.Chatbot(label="Academic assistant")
                    manager_chat_input = gr.Textbox(label="Chat Input")
                    manager_chat_button = gr.Button("Send to manager")
                with gr.Column(scale=1):
                    preview_button = gr.Button("Preview Selected File")
                    file_preview = gr.Markdown(label="File Preview")

    # Event connections
    login_button.click(
        on_login,
        inputs=[username_input],
        outputs=[login_output, login_tab, project_creation_tab, project_workspace_tab, token_state, current_project, project_dropdown]
    ).then(
        lambda token, project: get_project_files(token, project),
        inputs=[token_state, current_project],
        outputs=[file_list]
    )

    create_empty_project_btn.click(
        lambda token, name: on_create_project(token, name, "empty"),
        inputs=[token_state, new_project_input],
        outputs=[create_project_output, current_project, project_dropdown, file_list, project_dropdown]
    )

    create_pilot_project_btn.click(
        lambda token, name: on_create_project(token, name, "pilot"),
        inputs=[token_state, new_project_input],
        outputs=[create_project_output, current_project, project_dropdown, file_list, project_dropdown]
    )

    project_dropdown.change(
        on_project_select,
        inputs=[token_state, project_dropdown],
        outputs=[current_project, file_list]
    )

    file_list.change(
        on_file_select,
        inputs=[token_state, current_project, file_list],
        outputs=[selected_files]
    )

    preview_button.click(
        preview_file,
        inputs=[token_state, current_project, selected_files],
        outputs=[file_preview]
    )

    creator_chat_button.click(
        on_chat_send_to_creator,
        inputs=[token_state, current_project, creator_chat_input],
        outputs=[creator_chat_input, creator_chat_output]
    )

    manager_chat_button.click(
        on_chat_send_to_manager,
        inputs=[token_state, current_project, manager_chat_input, chat_history],
        outputs=[manager_chat_input, manager_chat_output]
    )

    upload_button.upload(
        upload_file,
        inputs=[token_state, current_project, upload_button],
        outputs=[create_project_output, file_list]
    )

    # Add this new event to update project dropdown when workspace tab becomes visible
    project_workspace_tab.select(
        update_project_dropdown,
        inputs=[token_state],
        outputs=[project_dropdown]
    )

app.launch()