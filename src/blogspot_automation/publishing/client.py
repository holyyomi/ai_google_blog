import json
import logging
from blogspot_automation.config import Settings
from blogspot_automation.utils.network import post_json_with_retry

logger = logging.getLogger(__name__)


def _build_custom_metadata(description: str) -> str:
    """⚠️ 2026-07-25 실측: Blogger API v3는 이 값을 **저장하지 않는다**.

    테스트 초안을 만들어 `searchDescription`·`customMetaData`를 함께 전송한 뒤
    INSERT 응답과 `view=AUTHOR` 재조회를 확인한 결과 두 필드 모두 응답에 없고
    영속되지도 않았다(라이브 발행글 3건도 동일하게 None). 즉 자동 발행 경로로는
    글별 `<meta name="description">`을 만들 수 없다. Blogger 대시보드의
    "검색 설명 사용" 토글이 ON이어도(요미님 확인) 마찬가지다 — 그 토글은
    **블로그 단위** 설명(og:description으로 렌더됨)에만 관여한다.

    → 결론: 글별 SERP 스니펫은 Blogspot이 폴백으로 쓰는 **첫 문단**으로만 제어
    가능하다. 그래서 lede(AI_OVERVIEW_TARGET_ANSWER)를 주제별 확정 사실로 시작하게
    만든 변경(answer_engine_policy)이 스니펫 개별화의 유일한 레버다.
    이 함수는 하위호환·무해성 때문에 남겨둔다(전송해도 무시될 뿐). 이 값이 먹는다고
    가정한 새 로직을 얹지 말 것. `docs/INDEXABILITY_RUNBOOK.md` B항 참고.
    """
    clean = " ".join((description or "").split()).strip()
    return json.dumps(
        {
            "description": clean,
            "searchDescription": clean,
            "metaDescription": clean,
            "itemprop:description": clean,
        },
        ensure_ascii=False,
    )


class BloggerClient:
    def __init__(self, settings: Settings) -> None:
        self.client_id = (settings.blogger_client_id or "").strip()
        self.client_secret = (settings.blogger_client_secret or "").strip()
        self.refresh_token = (settings.blogger_refresh_token or "").strip()
        self.blog_id = (settings.blogger_blog_id or "").strip()
        if not all([self.client_id, self.client_secret, self.refresh_token, self.blog_id]):
            raise ValueError("Google Blogger credentials are not fully set in config.")

    def _get_access_token(self) -> str:
        import urllib.request
        import urllib.parse
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                if "access_token" not in result:
                    raise RuntimeError(f"Failed to get access token: {result}")
                return result["access_token"]
        except Exception as e:
            logger.error(f"OAuth token refresh failed: {e}")
            raise

    def publish_post(
        self,
        title: str,
        article_html: str,
        labels: list[str] | None = None,
        meta_description: str = "",
        permalink_slug: str = "",
        is_draft: bool = False,
    ) -> dict[str, object]:
        from blogspot_automation.services.seo_policy import (
            build_english_permalink_slug,
            normalize_labels,
            normalize_search_description,
            url_matches_permalink_slug,
        )

        token = self._get_access_token()
        normalized_labels = normalize_labels(labels)
        description = normalize_search_description(
            title=title,
            description=meta_description,
            html=article_html,
        )
        slug = build_english_permalink_slug(
            title=permalink_slug or title,
            topic=title,
            labels=normalized_labels,
        )
        slug_title = slug.replace("-", " ")
        payload = {
            "kind": "blogger#post",
            "blog": {"id": self.blog_id},
            "title": slug_title,
            "content": article_html,
            "labels": normalized_labels,
            "customMetaData": _build_custom_metadata(description),
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/?isDraft=true"
            
        res = post_json_with_retry(
            url=url,
            headers=headers,
            payload=payload,
            operation_name="blogger_publish",
            logger=logger
        )
        data = json.loads(res)
        post_id = str(data.get("id") or "")
        if not post_id:
            raise RuntimeError(f"Blogger insert did not return a post id: {data}")

        permalink_slug_matches = True
        permalink_warning = ""
        try:
            patch_payload = {
                "kind": "blogger#post",
                "id": post_id,
                "blog": {"id": self.blog_id},
                "title": title,
                "content": article_html,
                "labels": normalized_labels,
                "customMetaData": _build_custom_metadata(description),
            }
            patch_url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}"
            if not is_draft:
                publish_url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}/publish"
                published = post_json_with_retry(
                    url=publish_url,
                    headers={"Authorization": f"Bearer {token}"},
                    payload=None,
                    operation_name="blogger_publish_draft",
                    logger=logger,
                )
                data = json.loads(published)
                final_url = str(data.get("url") or "")
                if final_url and not url_matches_permalink_slug(final_url, slug):
                    permalink_slug_matches = False
                    permalink_warning = (
                        "Blogger published URL is missing the expected English permalink slug: "
                        f"expected={slug!r} returned_url={final_url!r}"
                    )
                    logger.warning(
                        "Blogger permalink warning: expected=%r returned_url=%r post_id=%s",
                        slug,
                        final_url,
                        post_id,
                    )
                patched = post_json_with_retry(
                    url=patch_url,
                    headers=headers,
                    payload=patch_payload,
                    operation_name="blogger_patch_title_after_permalink_seed",
                    logger=logger,
                    method="PATCH",
                )
                data = json.loads(patched)
            else:
                patched = post_json_with_retry(
                    url=patch_url,
                    headers=headers,
                    payload=patch_payload,
                    operation_name="blogger_patch_title_after_permalink_seed",
                    logger=logger,
                    method="PATCH",
                )
                data = json.loads(patched)
        except Exception:
            self._cleanup_failed_post(post_id=post_id, token=token)
            raise

        return {
            "id": data.get("id"),
            "url": data.get("url"),
            "status": data.get("status"),
            "permalink_slug": slug,
            "permalink_slug_matches": permalink_slug_matches,
            "permalink_warning": permalink_warning,
            "search_description": description,
        }

    def _cleanup_failed_post(self, *, post_id: str, token: str) -> None:
        if not post_id:
            return
        delete_url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}"
        try:
            post_json_with_retry(
                url=delete_url,
                headers={"Authorization": f"Bearer {token}"},
                payload=None,
                operation_name="blogger_delete_failed_post",
                logger=logger,
                method="DELETE",
                read_timeout=60,
                backoff_seconds=(2,),
            )
            logger.info("Deleted failed Blogger post draft/live cleanup post_id=%s", post_id)
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.warning(
                "Failed to delete Blogger post after publish error: post_id=%s error=%s",
                post_id,
                cleanup_exc,
            )

    def delete_post(self, post_id: str) -> bool:
        post_id = str(post_id or "").strip()
        if not post_id:
            return False
        token = self._get_access_token()
        delete_url = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/{post_id}"
        post_json_with_retry(
            url=delete_url,
            headers={"Authorization": f"Bearer {token}"},
            payload=None,
            operation_name="blogger_delete_post",
            logger=logger,
            method="DELETE",
            read_timeout=60,
            backoff_seconds=(2,),
        )
        logger.info("Deleted Blogger post post_id=%s", post_id)
        return True
