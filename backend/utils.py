def validate_github_url(url: str) -> bool:
  """Validate if the provided string is a GitHub URL."""
  return url.startswith(("https://github.com/", "http://github.com/"))


def get_repo_name(url: str) -> str:
  """Extract the repository name from a valid GitHub URL."""
  return url.rstrip("/").split("/")[-1].replace(".git", "")