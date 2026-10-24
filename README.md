# Instagram Influencer Analysis

An automated Instagram influencer data collection and analysis system developed as part of the SR NEXT Self-Guided Data Project Program.

## Overview

This project collects publicly available Instagram profile information, organizes influencer profiles by niche, derives engagement and posting-activity metrics, and supports influencer ranking and automation-pattern analysis using machine learning.

The system combines browser-based profile data collection, Instagram profile extraction, data processing, and trained machine learning models to build a structured dataset for influencer analysis.

## Key Features

- **Influencer Discovery:** Collects and organizes Instagram usernames across multiple content niches.
- **Profile Data Collection:** Retrieves profile information such as display name, follower count, biography, category, and publicly available contact details.
- **Engagement Analysis:** Calculates engagement rates using available post interaction data.
- **Posting Activity Analysis:** Derives posting-frequency metrics from available post timestamps.
- **Hashtag Analysis:** Extracts hashtags from accessible profile and post content.
- **Automation Analysis:** Uses a trained machine learning model to identify potential automation-related account patterns.
- **Influencer Ranking:** Uses engagement and profile-related features to support influencer ranking.
- **Structured Output:** Stores collected profiles and processing results in CSV format for further analysis.

## Project Architecture

```text
Instamodels/
├── main.py
├── import_insta.py
├── collect_influencers.py
├── collect_playwright.py
├── playwright_login.py
├── config.yaml
├── req.txt
│
├── data/
│   └── usernames/
│       ├── all_usernames.txt
│       ├── final_names.txt
│       └── <niche>.txt
│
├── scraper/
│   ├── instagram_discovery.py
│   └── username_store.py
│
├── model/
│   ├── rank_influencers.py
│   ├── train_automation_model.py
│   ├── test_model.py
│   ├── automation_model.pkl
│   └── engagement_model.pkl
│
└── results/
    ├── all_usernames_results.csv
    ├── all_usernames_skipped.csv
    └── all_usernames_results.csv.done_usernames.txt
```

*The directory tree summarizes the main components; individual files may vary depending on the local setup.*

## Technology Stack

- **Python** — core implementation and data processing
- **Playwright** — browser automation and profile data retrieval
- **Instaloader** — Instagram profile and post extraction
- **Pandas / CSV** — structured data processing and storage
- **Scikit-learn** — machine learning model training and inference
- **Pickle** — serialization of trained models

## Data Collection Workflow

1. **Username Preparation:** Load usernames from text or CSV files and organize them by content niche.
2. **Profile Retrieval:** Retrieve accessible Instagram profile information using the configured collection method.
3. **Profile Filtering:** Apply follower-count constraints and handle inaccessible profiles or collection errors.
4. **Metric Extraction:** Process available post interactions and timestamps to derive engagement and posting-activity metrics.
5. **Content Analysis:** Extract relevant hashtags and publicly available contact information where accessible.
6. **Data Export:** Write processed profiles to CSV and record skipped profiles with their corresponding reasons.
7. **Model-Based Analysis:** Use the available trained models and ranking pipeline for further account analysis.

## Supported Niches

The project organizes influencer profiles across niches including:

- Technology
- Fashion
- Fitness
- Food
- Travel
- Business
- Education
- Gaming
- Music
- Photography
- Beauty
- Health and Wellness
- Sports
- Entertainment
- Art and Design
- Pets and Animals

Actual coverage depends on the input username lists and the categories supported by the configured scripts.

## Dataset Schema

The main results CSV uses the following columns:

| Column | Description |
|---|---|
| `Name` | Instagram display name |
| `Followers` | Follower count |
| `Category` | Content niche assigned to the profile |
| `Engagement Rate (%)` | Engagement metric recorded for the profile |
| `Contact` | Publicly available contact information, when found |
| `Posting Frequency (per month)` | Posting-frequency metric |
| `Hashtags` | Relevant hashtags associated with the profile |
| `Notes` | Additional profile observations |

The skipped-profiles CSV records usernames that could not be included and the corresponding processing reason. The progress file helps prevent usernames already processed from being repeatedly attempted.

## Machine Learning Components

### Automation Analysis

The automation-analysis component uses a serialized model trained through `model/train_automation_model.py`. The model can be loaded by the inference pipeline to evaluate account-related features.

### Influencer Ranking

The ranking component in `model/rank_influencers.py` supports ordering profiles using the features available to the pipeline. The serialized model artifacts are stored under `model/`.

Model predictions depend on the features, training data, and preprocessing used by the corresponding implementation.

## Setup

### Prerequisites

- Python 3.10 or a compatible version for the installed dependencies
- Git
- A supported browser installation for Playwright
- Instagram access and a configured session where required by the collection scripts

### Installation

Clone the repository:

```bash
git clone https://github.com/vivek-sai5182/InstaAnalyser.git
cd InstaAnalyser
```

Create and activate a virtual environment on Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r req.txt
```

Install the required Playwright browser if the selected script uses it:

```bash
playwright install chromium
```

## Output Files

- `all_usernames_results.csv` — structured influencer profile data.
- `all_usernames_skipped.csv` — profiles excluded during processing and associated reasons.
- `all_usernames_results.csv.done_usernames.txt` — processing progress used for resumable collection.
- Model files under `model/` — serialized machine learning artifacts used by the analysis pipeline.

## Reliability and Limitations

- Instagram may restrict requests, change its response structure, or require authentication.
- Private profiles and inaccessible posts may limit the available data.
- Public contact details may not be available for every account.
- Engagement and posting-frequency metrics depend on the information accessible to the configured collection method.
- Machine learning predictions are dependent on the training data and model features; they should be interpreted as analytical outputs rather than definitive proof of account behavior.
- Collection runs should respect Instagram's applicable terms, rate limits, and privacy requirements.

## Project Context

Developed as part of the **SR NEXT Self-Guided Data Project Program**, focusing on influencer data collection, structured analysis, and machine learning-assisted account evaluation.
