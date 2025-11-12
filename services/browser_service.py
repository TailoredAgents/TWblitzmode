"""
Browser Service for Web Search and Citation Management
Provides web search capabilities with citation tracking for the Master Agent

Features:
- Web search with result parsing and citation extraction
- Citation ID generation and management
- Integration with Master Agent session context
- Fallback messaging for failed searches
- Security-aware content filtering
"""

import asyncio
import logging
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Callable, Awaitable
from dataclasses import dataclass
from urllib.parse import urlparse
import json

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

@dataclass
class Citation:
    """Citation information for web search results"""
    id: str
    url: str
    title: str
    snippet: str
    domain: str
    retrieved_at: datetime
    relevance_score: float = 0.0

@dataclass
class SearchResult:
    """Enhanced web search result with citation information"""
    query: str
    results: List[Citation]
    total_found: int
    search_time_ms: int
    status: str
    error_message: Optional[str] = None
    search_engine: Optional[str] = None
    cached: bool = False

class BrowserService:
    """
    Web search and citation management service

    Provides intelligent web search capabilities for the Master Agent,
    with proper citation tracking and security filtering.
    """

    def __init__(self):
        self.citations_cache: Dict[str, Citation] = {}
        self.search_timeout = 10  # seconds
        self.max_results = 5
        self.max_snippet_length = 250
        self._request_semaphore = asyncio.Semaphore(4)
        self.engine_failures: Dict[str, Dict[str, Any]] = {}
        self.failure_threshold = 3
        self.failure_cooldown = timedelta(minutes=5)
        self.retry_attempts = 3
        self.retry_base_delay = 0.75
        self.allowed_schemes = {"http", "https"}
        self.blocked_host_prefixes = ("localhost", "127.", "169.254.", "::1", "::ffff:")
        self.blocked_domains = {"localhost", "metadata.google.internal"}

        # Enhanced search results caching
        self.search_cache: Dict[str, SearchResult] = {}
        self.cache_expiry_hours = 2

        # Multi-engine search configuration with fallbacks
        self.search_engines = [
            {
                "name": "duckduckgo",
                "url": "https://html.duckduckgo.com/html/",
                "enabled": True,
                "priority": 1,
                "timeout": 8,
                "retries": 3,
            },
            {
                "name": "searx",
                "url": "https://searx.org/search",
                "enabled": False,  # Disabled by default
                "priority": 2,
                "timeout": 10,
                "retries": 2,
            }
        ]

        serpapi_key = os.getenv("SERPAPI_API_KEY")
        if serpapi_key:
            self.search_engines.append(
                {
                    "name": "serpapi",
                    "url": "https://serpapi.com/search.json",
                    "enabled": True,
                    "priority": 0,
                    "timeout": 8,
                    "retries": 2,
                    "api_key": serpapi_key,
                }
            )

        # Enhanced relevance scoring weights
        self.relevance_weights = {
            "title_match": 0.4,
            "snippet_match": 0.3,
            "domain_authority": 0.2,
            "freshness": 0.1
        }

        # Domain authority scores (simplified)
        self.domain_authority = {
            "wikipedia.org": 0.95,
            "bloomberg.com": 0.90,
            "reuters.com": 0.90,
            "wsj.com": 0.88,
            "forbes.com": 0.85,
            "linkedin.com": 0.82,
            "techcrunch.com": 0.80,
            "crunchbase.com": 0.78,
            "sec.gov": 0.95
        }

        logger.info("Enhanced BrowserService initialized with multi-engine search and advanced citation tracking")

    async def search(self, query: str, max_results: Optional[int] = None) -> SearchResult:
        """
        Enhanced web search with caching, multiple engines, and advanced citations

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            SearchResult with enhanced citations and metadata
        """
        start_time = time.time()
        max_results = max_results or self.max_results

        try:
            logger.info(f"Performing enhanced web search for: {query}")

            # Clean and prepare query
            clean_query = self._clean_search_query(query)
            if not clean_query:
                return SearchResult(
                    query=query,
                    results=[],
                    total_found=0,
                    search_time_ms=0,
                    status="error",
                    error_message="Invalid search query"
                )

            # Check cache first
            cache_key = f"{clean_query}_{max_results}"
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                logger.info(f"Returning cached search result for: {query}")
                return cached_result

            # Perform multi-engine search with fallbacks
            results, search_engine_used, provider_errors = await self._perform_enhanced_search(
                clean_query,
                max_results,
            )

            search_time_ms = int((time.time() - start_time) * 1000)

            if not results and provider_errors:
                failure_message = self._format_search_failure(provider_errors)
                return SearchResult(
                    query=query,
                    results=[],
                    total_found=0,
                    search_time_ms=search_time_ms,
                    status="error",
                    error_message=failure_message,
                    search_engine=search_engine_used or "none",
                )

            # Enhanced citation generation with relevance scoring
            citations = []
            for i, result in enumerate(results):
                citation = self._create_enhanced_citation(result, query, i)
                citations.append(citation)
                # Cache citation for later reference
                self.citations_cache[citation.id] = citation

            # Sort citations by relevance score
            citations.sort(key=lambda c: c.relevance_score, reverse=True)

            search_result = SearchResult(
                query=query,
                results=citations,
                total_found=len(citations),
                search_time_ms=search_time_ms,
                status="success",
                search_engine=search_engine_used
            )

            # Cache the result
            self._cache_result(cache_key, search_result)

            return search_result

        except Exception as e:
            search_time_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Enhanced web search failed for query '{query}': {e}")

            friendly_message = self._format_search_failure([str(e)])

            return SearchResult(
                query=query,
                results=[],
                total_found=0,
                search_time_ms=search_time_ms,
                status="error",
                error_message=friendly_message,
                search_engine="none"
            )

    async def search_executive(self, person_name: str, company: str = "") -> SearchResult:
        """
        Specialized search for executive information

        Args:
            person_name: Name of the person to search for
            company: Optional company name for context

        Returns:
            SearchResult with executive information and citations
        """
        # Construct targeted search query
        if company:
            query = f'"{person_name}" CEO "{company}"'
        else:
            query = f'"{person_name}" CEO OR "Chief Executive Officer"'

        return await self.search(query, max_results=3)

    async def search_company_info(self, company_name: str, info_type: str = "general") -> SearchResult:
        """
        Search for company information

        Args:
            company_name: Name of the company
            info_type: Type of information (general, executives, news)

        Returns:
            SearchResult with company information and citations
        """
        if info_type == "executives":
            query = f'"{company_name}" CEO OR executives OR leadership team'
        elif info_type == "news":
            query = f'"{company_name}" news OR recent OR announcement'
        else:
            query = f'"{company_name}" company information'

        return await self.search(query, max_results=4)

    def get_citation(self, citation_id: str) -> Optional[Citation]:
        """Get citation by ID"""
        return self.citations_cache.get(citation_id)

    def format_search_response(
        self,
        search_result: SearchResult,
        include_citations: bool = True
    ) -> str:
        """
        Format search results into a user-friendly response

        Args:
            search_result: SearchResult to format
            include_citations: Whether to include citation references

        Returns:
            Formatted response string
        """
        if search_result.status == "error":
            return f"I couldn't search for information about '{search_result.query}' due to: {search_result.error_message or 'Unknown error'}"

        if not search_result.results:
            return f"I couldn't find specific information about '{search_result.query}' in my web search. You might want to try a more specific query or check the company's official website."

        # Format results
        response_parts = []

        for i, citation in enumerate(search_result.results[:3], 1):
            snippet = citation.snippet
            if len(snippet) > self.max_snippet_length:
                snippet = snippet[:self.max_snippet_length] + "..."

            result_text = f"**{citation.title}**\n{snippet}"

            if include_citations:
                result_text += f" [[{citation.id}]]"

            response_parts.append(result_text)

        response = "\n\n".join(response_parts)

        # Add search metadata
        if include_citations and search_result.results:
            response += f"\n\n*Search completed in {search_result.search_time_ms}ms with {search_result.total_found} results*"

        return response

    async def _perform_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """
        Perform actual web search using available search engines

        Args:
            query: Cleaned search query
            max_results: Maximum results to return

        Returns:
            List of raw search results
        """
        results = []

        for engine in self.search_engines:
            if not engine["enabled"]:
                continue

            try:
                if engine["name"] == "duckduckgo":
                    engine_results = await self._search_duckduckgo(query, max_results)
                    results.extend(engine_results)

                # Stop if we have enough results
                if len(results) >= max_results:
                    break

            except Exception as e:
                logger.warning(f"Search engine {engine['name']} failed: {e}")
                continue

        return results[:max_results]

    async def _search_duckduckgo(self, query: str, max_results: int, timeout_seconds: int) -> List[Dict[str, Any]]:
        """
        Search using DuckDuckGo HTML interface

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of search results
        """
        params = {
            "q": query,
            "kl": "us-en",
            "safe": "moderate"
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        timeout = aiohttp.ClientTimeout(total=min(timeout_seconds, self.search_timeout))
        html: Optional[str] = None

        try:
            async with self._request_semaphore:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "https://html.duckduckgo.com/html/",
                        params=params,
                        headers=headers,
                    ) as response:
                        if response.status >= 400:
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=f"DuckDuckGo responded with status {response.status}",
                                headers=response.headers,
                            )
                        html = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error(f"DuckDuckGo search failed: {exc}")
            return []

        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        results: List[Dict[str, Any]] = []

        for container in soup.find_all('div', class_='result'):
            try:
                title_link = container.find('a', class_='result__a')
                if not title_link:
                    continue

                title = title_link.get_text(strip=True)
                url = title_link.get('href', '')

                sanitized_url = self._sanitize_url(url)
                if not title or not sanitized_url:
                    continue

                snippet_elem = container.find('a', class_='result__snippet')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                snippet = snippet[: self.max_snippet_length] + ("…" if len(snippet) > self.max_snippet_length else "")

                results.append({
                    "title": title,
                    "url": sanitized_url,
                    "snippet": snippet,
                    "source": "duckduckgo"
                })

                if len(results) >= max_results:
                    break

            except Exception as exc:
                logger.debug(f"Error parsing DuckDuckGo result: {exc}")
                continue

        return results

    def _clean_search_query(self, query: str) -> str:
        """
        Clean and validate search query

        Args:
            query: Raw search query

        Returns:
            Cleaned query string
        """
        if not query or not query.strip():
            return ""

        # Remove excessive whitespace
        cleaned = re.sub(r'\s+', ' ', query.strip())

        # Remove potentially harmful characters
        cleaned = re.sub(r'[<>"\';\\]', '', cleaned)

        # Limit length
        max_query_length = 200
        if len(cleaned) > max_query_length:
            cleaned = cleaned[:max_query_length]

        return cleaned

    def _create_citation(self, result: Dict[str, Any], original_query: str) -> Citation:
        """
        Create citation object from search result

        Args:
            result: Raw search result
            original_query: Original search query

        Returns:
            Citation object
        """
        # Generate unique citation ID
        citation_id = f"cite_{secrets.token_hex(6)}"

        # Extract domain from URL
        domain = "unknown"
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(result.get("url", ""))
            domain = parsed_url.netloc or "unknown"
        except:
            pass

        # Calculate relevance score (basic implementation)
        relevance_score = self._calculate_relevance(result, original_query)

        return Citation(
            id=citation_id,
            url=result.get("url", ""),
            title=result.get("title", "No title"),
            snippet=result.get("snippet", ""),
            domain=domain,
            retrieved_at=datetime.now(timezone.utc),
            relevance_score=relevance_score
        )

    def _calculate_relevance(self, result: Dict[str, Any], query: str) -> float:
        """
        Calculate basic relevance score for search result

        Args:
            result: Search result data
            query: Original search query

        Returns:
            Relevance score between 0.0 and 1.0
        """
        score = 0.0
        query_terms = query.lower().split()

        title = result.get("title", "").lower()
        snippet = result.get("snippet", "").lower()

        # Title matches are weighted more heavily
        for term in query_terms:
            if term in title:
                score += 0.3
            if term in snippet:
                score += 0.1

        # Normalize score
        max_possible_score = len(query_terms) * 0.4  # 0.3 + 0.1 per term
        if max_possible_score > 0:
            score = min(score / max_possible_score, 1.0)

        return score

    def format_citations_list(self, citation_ids: List[str]) -> str:
        """
        Format a list of citations for display

        Args:
            citation_ids: List of citation IDs to format

        Returns:
            Formatted citations text
        """
        if not citation_ids:
            return ""

        citations_text = "**Sources:**\n"
        for i, cid in enumerate(citation_ids, 1):
            citation = self.get_citation(cid)
            if citation:
                citations_text += f"{i}. [{citation.title}]({citation.url}) - {citation.domain}\n"

        return citations_text

    def cleanup_old_citations(self, hours_old: int = 24):
        """
        Clean up old citations from cache

        Args:
            hours_old: Remove citations older than this many hours
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_old)

        old_citations = [
            cid for cid, citation in self.citations_cache.items()
            if citation.retrieved_at < cutoff_time
        ]

        for citation_id in old_citations:
            del self.citations_cache[citation_id]

        if old_citations:
            logger.info(f"Cleaned up {len(old_citations)} old citations")

    async def _perform_enhanced_search(self, query: str, max_results: int) -> Tuple[List[Dict[str, Any]], str, List[str]]:
        """
        Enhanced multi-engine search with fallbacks and performance optimization

        Args:
            query: Cleaned search query
            max_results: Maximum results to return

        Returns:
            Tuple of (results, search_engine_used, provider_errors)
        """
        search_engine_used = "none"
        provider_errors: List[str] = []

        # Sort engines by priority
        sorted_engines = sorted(
            [e for e in self.search_engines if e["enabled"]],
            key=lambda x: x["priority"]
        )

        for engine in sorted_engines:
            engine_name = engine["name"]

            if not self._engine_available(engine_name):
                logger.warning(f"Skipping {engine_name} due to circuit breaker cooldown")
                provider_errors.append(f"{engine_name}: temporarily unavailable (cooldown)")
                continue

            timeout = engine.get("timeout", self.search_timeout)
            retries = engine.get("retries")

            async def execute_engine() -> List[Dict[str, Any]]:
                if engine_name == "duckduckgo":
                    return await self._search_duckduckgo(query, max_results, timeout)
                if engine_name == "searx":
                    return await self._search_searx(query, max_results, timeout)
                if engine_name == "serpapi":
                    return await self._search_serpapi(
                        query,
                        max_results,
                        timeout,
                        engine.get("api_key", ""),
                    )
                raise ValueError(f"Unsupported search engine '{engine_name}'")

            try:
                engine_results = await self._with_retries(
                    f"{engine_name}_search",
                    execute_engine,
                    attempts=retries,
                    base_delay=self.retry_base_delay,
                )
            except Exception as e:
                logger.warning(f"Search engine {engine_name} failed: {e}")
                self._record_engine_failure(engine_name)
                provider_errors.append(f"{engine_name}: {e}")
                continue

            if engine_results:
                search_engine_used = engine_name
                logger.info(f"Search successful with {engine_name}: {len(engine_results)} results")
                self._reset_engine_failure(engine_name)
                return engine_results[:max_results], search_engine_used, []

            logger.info(f"{engine_name} returned no results; evaluating next provider")
            self._reset_engine_failure(engine_name)
            # Try the next provider for additional coverage

        return [], search_engine_used, provider_errors

    def _engine_available(self, engine_name: str) -> bool:
        """Check whether a search engine can be used based on recent failures."""
        state = self.engine_failures.get(engine_name)
        if not state:
            return True

        failure_count = state.get("count", 0)
        last_failure = state.get("last_failure", datetime.now(timezone.utc))

        if failure_count < self.failure_threshold:
            return True

        if datetime.now(timezone.utc) - last_failure > self.failure_cooldown:
            self.engine_failures.pop(engine_name, None)
            return True

        return False

    def _record_engine_failure(self, engine_name: str) -> None:
        """Record a failure for the search engine."""
        state = self.engine_failures.setdefault(
            engine_name,
            {"count": 0, "last_failure": datetime.now(timezone.utc)},
        )
        state["count"] = state.get("count", 0) + 1
        state["last_failure"] = datetime.now(timezone.utc)

    def _reset_engine_failure(self, engine_name: str) -> None:
        """Reset the failure counter for a search engine."""
        if engine_name in self.engine_failures:
            self.engine_failures.pop(engine_name, None)

    async def _with_retries(
        self,
        operation_name: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        attempts: Optional[int] = None,
        base_delay: Optional[float] = None,
    ) -> Any:
        """Execute an async operation with exponential backoff retries."""

        total_attempts = max(1, attempts or self.retry_attempts)
        delay = base_delay or self.retry_base_delay
        last_error: Optional[Exception] = None

        for attempt in range(1, total_attempts + 1):
            try:
                return await coro_factory()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "%s attempt %s/%s failed: %s",
                    operation_name,
                    attempt,
                    total_attempts,
                    exc,
                )
                if attempt == total_attempts:
                    break
                jitter = random.uniform(0, delay * 0.3)
                await asyncio.sleep(delay + jitter)
                delay *= 2

        if last_error:
            raise last_error

        raise RuntimeError(f"{operation_name} failed without raising explicit exception")  # pragma: no cover

    def _format_search_failure(self, provider_errors: List[str]) -> str:
        """Create user-facing messaging when all providers fail."""

        if not provider_errors:
            return (
                "All web search providers are currently unavailable. "
                "Please try again in a few minutes or refine your request."
            )

        detail_limit = 3
        trimmed = provider_errors[:detail_limit]
        error_message = "; ".join(trimmed)
        if len(provider_errors) > detail_limit:
            error_message += f" (+{len(provider_errors) - detail_limit} more)"

        return (
            "All web search providers are currently unavailable. "
            f"Provider errors: {error_message}. "
            "Please retry in a few minutes or refine your request while I continue monitoring availability."
        )

    def _sanitize_url(self, url: str) -> Optional[str]:
        """Sanitize and validate URLs returned by search providers."""
        if not url:
            return None

        cleaned = url.strip()
        if not cleaned:
            return None

        try:
            parsed = urlparse(cleaned)
        except Exception:
            return None

        scheme = (parsed.scheme or "").lower()
        if scheme not in self.allowed_schemes:
            return None

        host = (parsed.hostname or "").lower()
        if not host:
            return None

        if any(host.startswith(prefix) for prefix in self.blocked_host_prefixes):
            return None

        if host in self.blocked_domains:
            return None

        return parsed.geturl()

    async def _search_searx(self, query: str, max_results: int, timeout_seconds: int) -> List[Dict[str, Any]]:
        """
        Search using SearX metasearch engine as fallback

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of search results
        """
        try:
            params = {
                "q": query,
                "format": "json",
                "language": "en-US",
                "safesearch": "1"
            }

            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            }

            timeout = aiohttp.ClientTimeout(total=min(timeout_seconds, self.search_timeout))

            async with self._request_semaphore:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get("https://searx.org/search", params=params, headers=headers, ssl=False) as response:
                        if response.status >= 400:
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=f"SearX responded with status {response.status}",
                                headers=response.headers,
                            )
                        data = await response.json()

            results = []

            for item in data.get("results", [])[:max_results]:
                sanitized_url = self._sanitize_url(item.get("url", ""))
                title = item.get("title", "").strip()
                if sanitized_url and title:
                    snippet = (item.get("content", "") or "").strip()
                    if len(snippet) > self.max_snippet_length:
                        snippet = f"{snippet[:self.max_snippet_length]}…"
                    results.append({
                        "title": title,
                        "url": sanitized_url,
                        "snippet": snippet,
                        "source": "searx"
                    })

            return results

        except Exception as e:
            logger.error(f"SearX search failed: {e}")
            return []

    async def _search_serpapi(
        self,
        query: str,
        max_results: int,
        timeout_seconds: int,
        api_key: str,
    ) -> List[Dict[str, Any]]:
        """Search using SerpAPI when API credentials are available."""

        if not api_key:
            raise ValueError("SERPAPI_API_KEY is not configured")

        params = {
            "q": query,
            "api_key": api_key,
            "engine": "google",
            "hl": "en",
            "num": max_results,
        }

        timeout = aiohttp.ClientTimeout(total=min(timeout_seconds, self.search_timeout))

        try:
            async with self._request_semaphore:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "https://serpapi.com/search.json",
                        params=params,
                    ) as response:
                        if response.status >= 400:
                            raise aiohttp.ClientResponseError(
                                request_info=response.request_info,
                                history=response.history,
                                status=response.status,
                                message=f"SerpAPI responded with status {response.status}",
                                headers=response.headers,
                            )
                        data = await response.json()

            if "error" in data:
                raise RuntimeError(data["error"])

            results = []
            for item in data.get("organic_results", [])[:max_results]:
                link = self._sanitize_url(item.get("link", ""))
                title = (item.get("title") or "").strip()
                if not link or not title:
                    continue

                snippet = (item.get("snippet") or "").strip()
                if len(snippet) > self.max_snippet_length:
                    snippet = f"{snippet[:self.max_snippet_length]}…"

                results.append(
                    {
                        "title": title,
                        "url": link,
                        "snippet": snippet,
                        "source": "serpapi",
                    }
                )

            return results

        except Exception as exc:  # noqa: BLE001
            logger.error(f"SerpAPI search failed: {exc}")
            raise

    def _get_cached_result(self, cache_key: str) -> Optional[SearchResult]:
        """Get cached search result if not expired"""
        if cache_key not in self.search_cache:
            return None

        cached_result = self.search_cache[cache_key]

        if not cached_result.results:
            return None

        # Check if cache has expired
        cache_age_hours = (datetime.now(timezone.utc) - cached_result.results[0].retrieved_at).total_seconds() / 3600
        if cache_age_hours > self.cache_expiry_hours:
            del self.search_cache[cache_key]
            return None

        # Mark as cached and return
        cached_result.cached = True
        return cached_result

    def _cache_result(self, cache_key: str, result: SearchResult):
        """Cache search result for future use"""
        self.search_cache[cache_key] = result

        # Limit cache size
        if len(self.search_cache) > 100:
            # Remove oldest entries
            def _cache_sort_key(cache_key: str) -> datetime:
                cached = self.search_cache[cache_key]
                if cached.results:
                    return cached.results[0].retrieved_at
                return datetime.now(timezone.utc)

            oldest_key = min(self.search_cache.keys(), key=_cache_sort_key)
            self.search_cache.pop(oldest_key, None)

    def _create_enhanced_citation(self, result: Dict[str, Any], original_query: str, rank: int) -> Citation:
        """
        Create enhanced citation with improved relevance scoring

        Args:
            result: Raw search result
            original_query: Original search query
            rank: Position in search results (0-based)

        Returns:
            Enhanced Citation object
        """
        # Generate unique citation ID with timestamp
        citation_id = f"cite_{secrets.token_hex(4)}_{int(time.time())}_{rank}"

        # Extract and validate domain
        domain = self._extract_domain(result.get("url", ""))

        # Enhanced relevance calculation
        relevance_score = self._calculate_enhanced_relevance(result, original_query, rank, domain)

        # Clean and enhance snippet
        snippet = self._clean_snippet(result.get("snippet", ""))

        return Citation(
            id=citation_id,
            url=result.get("url", ""),
            title=result.get("title", "No title"),
            snippet=snippet,
            domain=domain,
            retrieved_at=datetime.now(timezone.utc),
            relevance_score=relevance_score
        )

    def _calculate_enhanced_relevance(self, result: Dict[str, Any], query: str, rank: int, domain: str) -> float:
        """
        Enhanced relevance scoring with multiple factors

        Args:
            result: Search result data
            query: Original search query
            rank: Position in results (0-based)
            domain: Extracted domain

        Returns:
            Enhanced relevance score between 0.0 and 1.0
        """
        score = 0.0
        query_terms = query.lower().split()

        title = result.get("title", "").lower()
        snippet = result.get("snippet", "").lower()

        # 1. Title matching (weighted 40%)
        title_matches = sum(1 for term in query_terms if term in title)
        title_score = (title_matches / len(query_terms)) if query_terms else 0
        score += title_score * self.relevance_weights["title_match"]

        # 2. Snippet matching (weighted 30%)
        snippet_matches = sum(1 for term in query_terms if term in snippet)
        snippet_score = (snippet_matches / len(query_terms)) if query_terms else 0
        score += snippet_score * self.relevance_weights["snippet_match"]

        # 3. Domain authority (weighted 20%)
        domain_score = self.domain_authority.get(domain, 0.5)
        score += domain_score * self.relevance_weights["domain_authority"]

        # 4. Position penalty (weighted 10%) - higher positions get slightly lower scores
        position_score = max(0, 1.0 - (rank * 0.05))  # 5% penalty per position
        score += position_score * self.relevance_weights["freshness"]

        return min(score, 1.0)

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL with validation"""
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()

            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]

            return domain or "unknown"
        except:
            return "unknown"

    def _clean_snippet(self, snippet: str) -> str:
        """Clean and format snippet text"""
        if not snippet:
            return ""

        # Remove extra whitespace and newlines
        cleaned = re.sub(r'\s+', ' ', snippet.strip())

        # Remove common HTML entities
        cleaned = cleaned.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')

        # Remove ellipsis and truncation markers
        cleaned = re.sub(r'\s*\.\.\.\s*$', '', cleaned)

        return cleaned

    def get_search_statistics(self) -> Dict[str, Any]:
        """Get search service statistics for monitoring"""
        return {
            "citations_cached": len(self.citations_cache),
            "searches_cached": len(self.search_cache),
            "cache_hit_rate": getattr(self, '_cache_hits', 0) / max(getattr(self, '_total_searches', 1), 1),
            "engines_configured": len([e for e in self.search_engines if e["enabled"]]),
            "domain_authorities": len(self.domain_authority)
        }

# Global browser service instance
browser_service = BrowserService()