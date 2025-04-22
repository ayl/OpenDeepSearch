import os
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, TypeVar, Generic, Union
from abc import ABC, abstractmethod

import requests, json

T = TypeVar('T')

class SearchAPIException(Exception):
    """Custom exception for Search API related errors"""
    pass

class SerperAPIException(SearchAPIException):
    """Custom exception for Serper API related errors"""
    pass

class SearXNGException(SearchAPIException):
    """Custom exception for SearXNG related errors"""
    pass

@dataclass
class SerperConfig:
    """Configuration for Serper API"""
    api_key: str
    api_url: str = "https://google.serper.dev/search"
    default_location: str = 'us'
    timeout: int = 10

    @classmethod
    def from_env(cls) -> 'SerperConfig':
        """Create config from environment variables"""
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            raise SerperAPIException("SERPER_API_KEY environment variable not set")
        return cls(api_key=api_key)

@dataclass
class SearXNGConfig:
    """Configuration for SearXNG instance"""
    instance_url: str
    api_key: Optional[str] = None
    default_location: str = 'all'
    timeout: int = 10

    @classmethod
    def from_env(cls) -> 'SearXNGConfig':
        """Create config from environment variables"""
        instance_url = os.getenv("SEARXNG_INSTANCE_URL")
        if not instance_url:
            raise SearXNGException("SEARXNG_INSTANCE_URL environment variable not set")
        api_key = os.getenv("SEARXNG_API_KEY")  # Optional
        return cls(instance_url=instance_url, api_key=api_key)

class SearchResult(Generic[T]):
    """Container for search results with error handling"""
    def __init__(self, data: Optional[T] = None, error: Optional[str] = None):
        self.data = data
        self.error = error
        self.success = error is None

    @property
    def failed(self) -> bool:
        return not self.success

class SearchAPI(ABC):
    """Abstract base class for search APIs"""
    @abstractmethod
    def get_sources(
        self,
        query: str,
        num_results: int = 8,
        stored_location: Optional[str] = None
    ) -> SearchResult[Dict[str, Any]]:
        """Get search results from the API"""
        pass

class SerperAPI(SearchAPI):
    def __init__(self, api_key: Optional[str] = None, config: Optional[SerperConfig] = None):
        if api_key:
            self.config = SerperConfig(api_key=api_key)
        else:
            self.config = config or SerperConfig.from_env()

        self.headers = {
            'X-API-KEY': self.config.api_key,
            'Content-Type': 'application/json'
        }

    @staticmethod
    def extract_fields(items: List[Dict[str, Any]], fields: List[str]) -> List[Dict[str, Any]]:
        """Extract specified fields from a list of dictionaries"""
        return [{key: item.get(key, "") for key in fields if key in item} for item in items]

    def get_sources(
        self,
        query: str,
        num_results: int = 8,
        stored_location: Optional[str] = None
    ) -> SearchResult[Dict[str, Any]]:
        """
        Fetch search results from Serper API.

        Args:
            query: Search query string
            num_results: Number of results to return (default: 8, max: 10)
            stored_location: Optional location string

        Returns:
            SearchResult containing the search results or error information
        """
        if not query.strip():
            return SearchResult(error="Query cannot be empty")

        try:
            search_location = (stored_location or self.config.default_location).lower()

            payload = {
                "q": query,
                "num": min(max(1, num_results), 10),
                "gl": search_location
            }

            response = requests.post(
                self.config.api_url,
                headers=self.headers,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            results = {
                'organic': self.extract_fields(
                    data.get('organic', []),
                    ['title', 'link', 'snippet', 'date']
                ),
                'topStories': self.extract_fields(
                    data.get('topStories', []),
                    ['title', 'imageUrl']
                ),
                'images': self.extract_fields(
                    data.get('images', [])[:6],
                    ['title', 'imageUrl']
                ),
                'graph': data.get('knowledgeGraph'),
                'answerBox': data.get('answerBox'),
                'peopleAlsoAsk': data.get('peopleAlsoAsk'),
                'relatedSearches': data.get('relatedSearches')
            }

            return SearchResult(data=results)

        except requests.RequestException as e:
            return SearchResult(error=f"API request failed: {str(e)}")
        except Exception as e:
            return SearchResult(error=f"Unexpected error: {str(e)}")

class Pubmed(SearchAPI):
    """API client for Pubmed search engine"""
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PUBMED_API_KEY")
        if not self.api_key:
            self.api_key = ""

    def get_sources(
        self,
        query: str,
        num_results: int = 8,
        stored_location: Optional[str] = None
    ) -> SearchResult[Dict[str, Any]]:
        """
        Fetch search results from Pubmed API.

        Args:
            query: Search query string
            num_results: Number of results to return (default: 8)
            stored_location: Optional location string

        Returns:
            SearchResult containing the search results or error information
        """
        from Bio import Entrez
        results = {
            'organic': [],
            'images': [],
            'topStories': [],  # SearXNG might not have direct equivalent
            'graph': None,     # SearXNG doesn't provide knowledge graph
            'answerBox': None, # SearXNG doesn't provide answer box
            'peopleAlsoAsk': None,
            'relatedSearches': []
        }


        # Always provide your email address to NCBI
        Entrez.email = "agent@example.com"
        # If you have an API key, you can add: Entrez.api_key = "YOUR_API_KEY"
        if self.api_key != "":
            Entrez.api_key = self.api_key

        # Step 1: Use esearch to get a list of PMIDs for your query
        search_handle = Entrez.esearch(db="pubmed", term=query, retmax=25, sort='relevance')
        search_results = Entrez.read(search_handle)
        search_handle.close()
        pmid_list = search_results["IdList"]
        # check if no results:
        if not pmid_list:
            return SearchResult(data=results)

        # Step 2: Use efetch to get article details for each PMID
        fetch_handle = Entrez.efetch(db="pubmed", id=pmid_list, rettype="xml")
        records = Entrez.read(fetch_handle)
        fetch_handle.close()
        organic_results = []

        for article in records["PubmedArticle"]:
            # Extract PMID
            pmid = article["MedlineCitation"]["PMID"]
            # Extract title
            title = article["MedlineCitation"]["Article"]["ArticleTitle"]
            # Extract abstract (if available)
            if "Abstract" in article["MedlineCitation"]["Article"]:
                abstract_parts = article["MedlineCitation"]["Article"]["Abstract"]["AbstractText"]
                # Join multiple parts if the abstract is split up
                if isinstance(abstract_parts, list):
                    abstract = " ".join(abstract_parts)
                else:
                    abstract = abstract_parts
            else:
                abstract = "No abstract available."
            # Extract publication date
            journal_info = article["MedlineCitation"]["Article"]["Journal"]["JournalIssue"]
            pub_date = journal_info.get("PubDate", "No publication date available")

            # Handle different formats of PubDate
            if isinstance(pub_date, dict):
              year = pub_date.get("Year", "")
              month = pub_date.get("Month", "")
              day = pub_date.get("Day", "")
              # Combine parts if available
              publication_date = " ".join(part for part in [year, month, day] if part)
            else:
              publication_date = pub_date  # Might be a string

            # Try to get the DOI from the article IDs and construct a full text URL
            doi_url = None
            pmc_url = None
            pubmed_url = None
            article_ids = article.get("PubmedData", {}).get("ArticleIdList", [])
            for article_id in article_ids:
                # Check if the id type is doi
                if article_id.attributes.get("IdType") == "doi":
                    doi_url = "https://doi.org/" + str(article_id)
                if article_id.attributes.get("IdType") == "pmc":
                    pmc_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{article_id}/"
                if article_id.attributes.get("IdType") == "pubmed":
                    pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{article_id}/"

            final_url = pubmed_url
            if pmc_url is not None:
                final_url = pmc_url
            organic_results.append({
                'title': title,
                'link': final_url,
                # grab the last 100 characters of the abstract
                'snippet': abstract[-100:],
                'date':publication_date,
            })
            if len(organic_results) >= num_results:
                break

        # Format results to match SerperAPI structure
        results['organic'] =  organic_results
        if False:
            print(json.dumps(results, indent=2))

        return SearchResult(data=results)




class SearXNGAPI(SearchAPI):
    """API client for SearXNG search engine"""

    def __init__(self, instance_url: Optional[str] = None, api_key: Optional[str] = None, config: Optional[SearXNGConfig] = None):
        if instance_url:
            self.config = SearXNGConfig(instance_url=instance_url, api_key=api_key)
        else:
            self.config = config or SearXNGConfig.from_env()

        self.headers = {'Content-Type': 'application/json'}
        if self.config.api_key:
            self.headers['X-API-Key'] = self.config.api_key

    def get_sources(
        self,
        query: str,
        num_results: int = 8,
        stored_location: Optional[str] = None
    ) -> SearchResult[Dict[str, Any]]:
        """
        Fetch search results from SearXNG instance.

        Args:
            query: Search query string
            num_results: Number of results to return (default: 8)
            stored_location: Optional location string (may not be supported by all instances)

        Returns:
            SearchResult containing the search results or error information
        """
        if not query.strip():
            return SearchResult(error="Query cannot be empty")

        try:
            # Ensure the instance URL ends with /search
            search_url = self.config.instance_url
            if not search_url.endswith('/search'):
                search_url = search_url.rstrip('/') + '/search'

            # Prepare parameters for SearXNG
            params = {
                'q': query,
                'format': 'json',
                'pageno': 1,
                'categories': 'general',
                'language': 'all',
                'time_range': None,
                'safesearch': 0,
                'engines': 'google,bing,duckduckgo',  # Default engines, can be customised
                'max_results': min(max(1, num_results), 20)  # Limit to reasonable range
            }

            # Add location if provided and supported
            if stored_location and stored_location != 'all':
                params['language'] = stored_location

            response = requests.get(
                search_url,
                headers=self.headers,
                params=params,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()

            # Transform SearXNG results to match SerperAPI format
            organic_results = []
            for result in data.get('results', [])[:num_results]:
                organic_results.append({
                    'title': result.get('title', ''),
                    'link': result.get('url', ''),
                    'snippet': result.get('content', ''),
                    'date': result.get('publishedDate', '')
                })

            # Extract image results if available
            image_results = []
            for result in data.get('results', []):
                if result.get('img_src'):
                    image_results.append({
                        'title': result.get('title', ''),
                        'imageUrl': result.get('img_src', '')
                    })
            image_results = image_results[:6]  # Limit to 6 images like SerperAPI

            # Format results to match SerperAPI structure
            results = {
                'organic': organic_results,
                'images': image_results,
                'topStories': [],  # SearXNG might not have direct equivalent
                'graph': None,     # SearXNG doesn't provide knowledge graph
                'answerBox': None, # SearXNG doesn't provide answer box
                'peopleAlsoAsk': None,
                'relatedSearches': data.get('suggestions', [])
            }

            return SearchResult(data=results)

        except requests.RequestException as e:
            return SearchResult(error=f"SearXNG API request failed: {str(e)}")
        except Exception as e:
            return SearchResult(error=f"Unexpected error with SearXNG: {str(e)}")


def create_search_api(
    search_provider: str = "serper",
    pubmed_api_key: Optional[str] = None,
    serper_api_key: Optional[str] = None,
    searxng_instance_url: Optional[str] = None,
    searxng_api_key: Optional[str] = None
) -> SearchAPI:
    """
    Factory function to create the appropriate search API client.

    Args:
        search_provider: The search provider to use ('serper' or 'searxng')
        serper_api_key: Optional API key for Serper
        searxng_instance_url: Optional SearXNG instance URL
        searxng_api_key: Optional API key for SearXNG instance

    Returns:
        An instance of a SearchAPI implementation

    Raises:
        ValueError: If an invalid search provider is specified
    """
    if search_provider.lower() == "serper":
        return SerperAPI(api_key=serper_api_key)
    elif search_provider.lower() == "searxng":
        return SearXNGAPI(instance_url=searxng_instance_url, api_key=searxng_api_key)
    elif search_provider.lower() == "pubmed":
        return Pubmed(api_key=pubmed_api_key)
    else:
        raise ValueError(f"Invalid search provider: {search_provider}. Must be 'serper' or 'searxng'")


if __name__ == "__main__":
    # Example usage
    search_api = create_search_api(search_provider="pubmed")
    result = search_api.get_sources("AMD CFH")
    if result.success:
        print("Search results:", result.__dict__)
    else:
        print("Error:", result.error)
