from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.models import SummarizeRequest, SummarizeResponse, ErrorResponse
from app.services.github_client import GitHubClient, GitHubClientError
from app.services.llm_summarizer import Summarizer, SummarizerError

router = APIRouter()


@router.post(
    "/summarize",
    response_model=SummarizeResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def summarize_repo(request: SummarizeRequest):
    github_client = GitHubClient()
    summarizer = Summarizer()

    # 1. Parse URL
    owner, repo = github_client.parse_github_url(request.github_url)

    # 2. Fetch repo data from GitHub
    try:
        repo_data = await github_client.fetch_repo_data(owner, repo)
    except GitHubClientError as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(message=e.message).model_dump(),
        )

    # 3. Summarize with LLM
    try:
        result = await summarizer.summarize(repo_data)
    except SummarizerError as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(message=e.message).model_dump(),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(message=f"Unexpected error: {str(e)}").model_dump(),
        )

    return SummarizeResponse(**result)
