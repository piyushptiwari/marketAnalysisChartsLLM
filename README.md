This app consist two folders
backend and frontend
to run frontend:
1- Install dependencies by running npm i or npm install
2- run npm start

to Run backend:
1- create venv and install dependencies from requirements.txt and activate virtual environment
2- run "python main.py" and backend will starting running on port 8001 that you can changes and you can access the backend api on 127.0.0.1:8000/docs

Add .env in backend folder and add key
#OpenAI details
AZURE_OPENAI_API_KEY="******COGAKvA"
AZURE_OPENAI_ENDPOINT="******0268.openai.azure.com"
AZURE_OPENAI_DEPLOYMENT_NAME="any-agent-supported-model-like-gpt-4o"

#Search and create your own google api and google search engine id
GOOGLE_API_KEY="*****06e915c0"
#YOUR_GOOGLE_SEARCH_ENGINE_ID_HERE
GOOGLE_CX_ID="*****e46be4fd1"
