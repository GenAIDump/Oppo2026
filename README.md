# File: Oppo/README.md  
# Oppo - LLM-Powered A2A Opposition Research Host (v0.1)

## Overview

Oppo is an advanced system designed for political opposition research, leveraging Large Language Models (LLMs) for analysis. It integrates automated data collection, sophisticated AI-powered analysis, and distribution via an Agent-to-Agent (A2A) protocol. It helps consuming agents (e.g., Democratic campaign agent cards) stay informed about statements, activities, and potential disinformation related to opposition candidates (initially focused on House Republicans).

**Key Features (v0.1 - LLM Integrated):**

* **Background Data Collection:** Includes modules for crawling and processing data from sources like FEC, Congress.gov, OpenSecrets, press releases, campaign websites, and Ballotpedia. Data is stored via the MCP Server.  
* **Social Media Listeners:** Includes listeners for specified YouTube channels and Telegram channels to ingest near real-time posts. Gets configuration via MCP Server, sends raw posts to A2A Host Ingestion.  
* **LLM-Powered Analysis Engine:**  
    * Utilizes configured LLMs (e.g., Gemini, OpenAI models - requires API keys) via an abstracted `LLM Interface`.  
    * **Contradiction Detection:** LLM analyzes new posts against historical context (fetched via MCP) for contradictions.  
    * **Disinformation Analysis:** LLM assesses posts for known disinformation narratives, problematic sourcing, and other markers (based on prompts).  
    * **Fact-Checking:** LLM attempts to verify factual claims within posts, potentially citing sources (reliability depends on LLM capabilities).  
    * **Evasion Detection:** LLM analyzes language for evasiveness.  
* **Decision Engine:** Scores posts based on combined LLM analysis results and determines significance/disinformation level. Updates scores via MCP Server.  
* **Neo4j Storage:** Uses a Neo4j graph database, accessed securely via the MCP Server, to store structured data about candidates, relationships, ingested social media posts (`SocialPost` subgraph), and LLM-derived analysis results (scores, explanations, flags).  
* **Modern Context Protocol (MCP) Server:** A dedicated FastAPI service acting as a secure gateway to the Neo4j database, handling data queries and updates requested by other internal services (Listeners, Analysis Engine, Scripts). Prevents direct database access from LLMs or other potentially untrusted agents.  
* **A2A Host API:** The main FastAPI application. Handles ingestion requests, orchestrates analysis calls (which use the LLM Interface), serves on-demand reports (fetching data via MCP), and distributes alerts/data to the A2A network based on Decision Engine triggers.

## Architecture Diagram

┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐  
│ Oppo System (v0.1 - LLM Powered w/ MCP) │  
│ │  
│ External APIs / Sources Internal Services / Components A2A Network │  
│┌─────────────────┐ ┌──────────────────────┐ MCP Req ┌────────────────┐ Store ┌───────────────┐ │  
││ LLM APIs │◀──┐ │ Listeners │─────────▶│ MCP Server │───────────▶│ │ │  
││ (Gemini, OpenAI │ │ │ (YT/TG) │ Config/ │ (DB Gateway) │ Post │ A2A Host │◀────────────▶│  
││ Claude, etc.) │ │ └──────────┬───────────┘ State Req└───────┬────────┘ Data │ (API, Ingest, │ A2A Agents │  
│├─────────────────┤ │ │ Scheduler Trigger │ Neo4j Client │ │ Distrib, Analysis)│ │  
││ YouTube API │◀──┼─────────────────┘ │ Interaction │ └──────┬────────┘ │  
│├─────────────────┤ │ ┌───────────────────┐ │ │ │ LLM Call │  
││ Telegram API │◀──┼─────▶│ Listener Manager │ │ ┌─▼───────────┐ │ │  
│├─────────────────┤ │ └───────────────────┘ └───────────▶│ Neo4j DB │ │ │  
││ Other Sources │◀──┼─┐ │ (Graph Store) │◀────┐ │ │  
││ (FEC, etc.) │ │ │ ┌───────────────────┐ └─────────────┘ │ │ │  
│└─────────────────┘ │ └─▶ │ Data Collection │ Store Historical Data (via MCP) ▲ │ │ │  
│ │ │ (Crawlers/Procs) │─────────────────────────────────────────────┘ │ │ │  
│ │ └───────────────────┘ │ │ │  
│ │ ┌───────────────────────────────────────────┘ │ │  
│ │ │ Context Req / Update Scores │ │  
│ │ ┌────────────────────────────────▼─────────────────────────────────┐ │ │  
│ │ │ Analysis Engine (in A2A Host) │ │ │  
│ │ │ ┌──────────────────────────┐ ┌─────────────────────────────┐ │ Call External │ │  
│ │ │ │ Base/Disinfo Analyzers │──▶│ LLM Interface (Multi-Model) │─┴───────────────┘ │  
│ │ │ │ (Uses LLMs for analysis) │ │ (Handles API Calls/Keys) │ │ │  
│ │ │ └──────────────┬───────────┘ └─────────────────────────────┘ │ │  
│ │ │ │ Results ┌─────────────────────────────┐ │ │  
│ │ │ └───────────────▶│ Decision Engine │─┐ Trigger │  
│ │ │ └─────────────────────────────┘ │ Distribution │  
│ │ └────────────────────────────────────────────────────────────────┘ │  
│ └────────────────────────────────────────────────────────────────────────────────────────────────────┘  
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘  
## Data Flow (LLM Integration)

1.  **Background Data Collection (Periodic):** `Data Collection` system fetches historical data, processors structure it and send requests to the `MCP Server` to store it in `Neo4j`.  
2.  **Listener Trigger (Periodic):** `Scheduler` triggers `Listener Manager`.  
3.  **Listener Config/State:** `Listener Manager` requests candidate channel info and last check state from the `MCP Server`.  
4.  **API Polling:** Listeners poll external platform APIs (YouTube, Telegram).  
5.  **Ingestion:** Listeners send new `SocialPost` data to the `A2A Host - Ingestion API`.  
6.  **Store Raw Post & Update State:** Ingestion endpoint requests `MCP Server` to store the raw `SocialPost` in Neo4j and update the listener state.  
7.  **Trigger Analysis:** Ingestion endpoint triggers the `Analysis Engine` (likely asynchronously).  
8.  **Fetch Context via MCP:** `Analysis Engine` sub-modules (e.g., Contradiction Detector) request necessary historical context from the `MCP Server`.  
9.  **LLM Analysis:**  
    * Analysis sub-modules format prompts using the new post data and fetched context.  
    * They call the `LLM Interface`, specifying the task and configured LLM provider/model.  
    * `LLM Interface` calls the external LLM API (e.g., Gemini API).  
    * Analysis sub-module parses the structured result (e.g., contradiction score, explanation) returned by the `LLM Interface`.  
10. **(Repeat step 9 for other analysis types: Disinfo, Fact-check, Evasion).**  
11. **Decision Making:** The `Decision Engine` receives structured, LLM-derived results and calculates final significance/disinformation scores.  
12. **Update Scores via MCP:** `Decision Engine` sends request to `MCP Server` to update the `SocialPost` node in Neo4j with scores/summaries.  
13. **A2A Distribution Trigger:** If scores exceed thresholds, `Decision Engine` triggers the `A2A Host - Distribution` logic.  
14. **Network Alert:** Distribution logic formats an A2A message and sends it to subscribed `A2A Agents`.  
15. **Reporting (On-Demand):** A2A agents query A2A Host; Host fetches report data (including LLM analysis summaries) via `MCP Server`.

## File Structure

Oppo/  
├── a2a_host/  
│ ├── init.py  
│ ├── a2a_protocol.py  
│ ├── auth.py  
│ ├── config.py  
│ ├── routers/  
│ │ ├── init.py  
│ │ └── opposition.py  
│ └── server.py  
├── analysis/  
│ ├── init.py  
│ ├── contradiction_detector.py  
│ ├── decision_engine.py  
│ ├── disinformation_analyzer.py  
│ ├── evasion_detector.py  
│ ├── fact_checker.py  
│ ├── llm_interface.py  
│ └── report_generator.py  
├── database/  
│ ├── init.py  
│ ├── data_models.py  
│ ├── modern_context_protocol.py  
│ └── neo4j_client.py  
├── data_collection/  
│ ├── init.py  
│ ├── crawlers/  
│ │ ├── init.py  
│ │ ├── ballotpedia_crawler.py  
│ │ ├── campaign_website_crawler.py  
│ │ ├── congress_crawler.py  
│ │ ├── fec_crawler.py  
│ │ ├── house_press_crawler.py  
│ │ └── opensecrets_crawler.py  
│ ├── processors/  
│ │ ├── init.py  
│ │ ├── ballotpedia_processor.py  
│ │ ├── campaign_website_processor.py  
│ │ ├── congress_processor.py  
│ │ ├── fec_processor.py  
│ │ ├── house_press_processor.py  
│ │ └── opensecrets_processor.py  
│ └── scheduler.py  
├── listeners/  
│ ├── init.py  
│ ├── listener_manager.py  
│ ├── telegram_listener.py  
│ └── youtube_listener.py  
├── scripts/  
│ ├── init.py  
│ └── ingest_candidates_csv.py  
├── tests/  
│ ├── init.py  
│ ├── test_a2a_host.py  
│ ├── test_analysis.py  
│ ├── test_database.py  
│ ├── test_data_collection.py  
│ └── test_listeners.py  
├── .env.example  
├── .gitignore  
├── docker-compose.yml  
├── Dockerfile  
├── pyproject.toml # Primary project definition file  
└── README.md # This file  
## Setup and Configuration

### Prerequisites

* Python 3.10+  
* Docker and Docker Compose (v2.x+)  
* Access to a Neo4j instance (v5+ recommended)  
* API Keys for desired LLMs (Google AI Studio/Vertex AI for Gemini, OpenAI platform, Anthropic, etc.)  
* API Keys for YouTube Data API v3 and a Telegram Bot Token.  
* Git  
* Pip (Python package installer)

### Installation

1.  **Clone the repository:**  
    ```bash  
    # Replace <your-repo-url> with the actual URL when available  
    git clone <your-repo-url> Oppo  
    cd Oppo  
    ```  
2.  **Create and activate a virtual environment (Recommended):**  
    ```bash  
    python -m venv venv  
    # On Linux/macOS:  
    source venv/bin/activate  
    # On Windows:  
    .venvScriptsactivate  
    ```  
3.  **Install dependencies using `pyproject.toml`:**  
    ```bash  
    # This installs the project and all dependencies listed in pyproject.toml  
    pip install .  
    # To install optional development dependencies:  
    # pip install .[dev]  
    # To install optional LLM SDKs (example):  
    # pip install .[openai,anthropic]  
    ```  
4.  **Set up Environment Variables:**  
    * Copy the example environment file: `cp .env.example .env`  
    * Edit the `.env` file with your specific credentials and API keys (see details below).

### Environment Variables (`.env`) Required

```ini  
# ---> Database <---  
NEO4J_URI=neo4j://neo4j:7687  
NEO4J_USERNAME=neo4j  
NEO4J_PASSWORD=your_neo4j_password_CHANGE_ME

# ---> Service URLs (Internal Docker Network) <---  
MCP_SERVER_URL="http://mcp_server:8001"  
A2A_HOST_INTERNAL_URL="http://a2a_host:8000"

# ---> Authentication <---  
SECRET_KEY=your_strong_random_jwt_secret_key_CHANGE_ME # For A2A Host user auth  
INTERNAL_SERVICE_API_KEY=your_strong_random_internal_api_key_CHANGE_ME # For service-to-service auth

# ---> Listener Keys <---  
YOUTUBE_API_KEY="YOUR_YOUTUBE_DATA_API_V3_KEY"  
TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"

# ---> LLM API Keys (Add keys ONLY for the models you intend to use) <---  
GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY_FOR_GEMINI" # From Google AI Studio or Cloud Console  
# OPENAI_API_KEY="YOUR_OPENAI_API_KEY"  
# ANTHROPIC_API_KEY="YOUR_ANTHROPIC_API_KEY"

# ---> LLM Configuration (Select provider/model for tasks) <---  
# Options: "GEMINI", "OPENAI", "ANTHROPIC" (match llm_interface.py implementation)  
CONTRADICTION_LLM_PROVIDER="GEMINI"  
DISINFO_LLM_PROVIDER="GEMINI"  
FACTCHECK_LLM_PROVIDER="GEMINI"  
EVASION_LLM_PROVIDER="GEMINI"  
# Optional: Specify models if needed (defaults can be set in llm_interface.py)  
GEMINI_MODEL_NAME="gemini-1.5-flash-latest" # Or "gemini-pro" etc.  
# OPENAI_MODEL_NAME="gpt-4o"  
# ANTHROPIC_MODEL_NAME="claude-3-haiku-20240307"

# ---> Optional: Background Data Collection API Keys <---  
# FEC_API_KEY=""  
# OPENSECRETS_API_KEY=""

# ---> Logging <---  
LOG_LEVEL="INFO" # DEBUG, INFO, WARNING, ERROR, CRITICAL

# ---> A2A Agent Secrets (Load dynamically/securely in production!) <---  
# Example only - DO NOT commit real secrets to Git  
# AGENT_1_ENDPOINT="[https://campaign1.example.com/a2a/receive](https://campaign1.example.com/a2a/receive)"  
# AGENT_1_SECRET="secret_for_campaign_1"

### **API Key / Service Setup Instructions**

1. **Neo4j Database:** Setup using Docker (recommended) or AuraDB as described previously. Ensure user/pass match .env. The docker-compose.yml assumes a service named neo4j.  
2. **YouTube Data API v3 Key:** Follow previous instructions (Google Cloud Console: Enable API, Create Key, **Restrict Key**). Add to .env. Monitor Quota. See: [https://console.cloud.google.com/](https://console.cloud.google.com/)  
3. **Telegram Bot Token:** Follow previous instructions (@BotFather on Telegram). Add token to .env. Add bot to target channels. See: [https://core.telegram.org/bots#botfather](https://core.telegram.org/bots#botfather)  
4. **LLM API Keys:**  
   * **Google (Gemini):** Go to [Google AI Studio](https://aistudio.google.com/app/apikey) or Google Cloud Console (Vertex AI API) to generate an API key. Enable the relevant API (e.g., Generative Language API or Vertex AI API). Add the key to .env as GOOGLE_API_KEY.  
   * **OpenAI:** Go to the [OpenAI Platform](https://platform.openai.com/api-keys) to create an API key. Add it to .env as OPENAI_API_KEY. Requires setting up billing.  
   * **Anthropic (Claude):** Go to the [Anthropic Console](https://console.anthropic.com/settings/keys) to create an API key. Add it to .env as ANTHROPIC_API_KEY. Requires access approval.  
5. **Internal Service API Key & JWT Secret:** Generate strong random strings (e.g., openssl rand -hex 32) and add them to .env.

## **Running the System (Docker Recommended)**

1. Ensure Docker is running.  
2. Ensure .env is configured.  
3. From the Oppo/ directory, run: docker-compose up --build -d  
4. **Services Started:** neo4j, mcp_server, a2a_host, listener_service.  
5. **Access:** API at http://localhost:8000, Neo4j Browser at http://localhost:7474. (Check docker-compose.yml for mapped ports).

## **Usage**

Interact via A2A protocol with http://localhost:8000 endpoints (or deployed URL). Use JWT for user auth. Listeners run automatically in the listener_service container. Use scripts/ingest_candidates_csv.py for initial candidate loading via MCP (run within a container or ensure local environment can reach MCP service).

Example CSV Ingestion (run from host machine, assuming docker-compose is up):

docker exec oppo-a2a-host python scripts/ingest_candidates_csv.py /app/path/to/your/gop_youtube.csv  
# Note: You might need to map the CSV file into the container via docker-compose volumes first,  
# or copy it using 'docker cp /path/on/host/gop_youtube.csv oppo-a2a-host:/app/gop_youtube.csv'.  
# Adjust the path inside the container accordingly.

## **Testing**

Run tests using pytest (requires pip install .[dev]):

pytest tests/

*(Note: Test files provide structure but require significant expansion for comprehensive coverage, especially for mocking

**License**

*Specify your preferred license here.*
