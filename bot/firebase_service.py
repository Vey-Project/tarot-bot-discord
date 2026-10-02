"""Firebase Firestore + Storage wrapper.

Singleton — :data:`firebase_service` is shared across the bot. All public
methods are sync because the underlying grpc client is blocking; async
variants (``async_*``) wrap them in :func:`asyncio.to_thread` so the event
loop stays responsive when called from command handlers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from .config import (
    FIREBASE_CREDENTIALS_PATH,
    FIREBASE_DATABASE_URL,
    FIREBASE_ENABLED,
    FIREBASE_MAX_TRANSPORT_RETRIES,
    FIREBASE_RETRY_BACKOFF,
    FIREBASE_STORAGE_BUCKET,
)

logger = logging.getLogger(__name__)

# Lazy firebase-admin import so the SDK is optional.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore, storage
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False


# Substrings that mark an error as worth another attempt. WinError 10054 is
# the connection being reset by the peer — the exact failure that fills
# bot.log on a host that briefly loses its route.
_TRANSIENT_MARKERS = (
    "connection aborted",
    "connectionreseterror",
    "connectionreset",
    "read timed out",
    "timed out",
    "unavailable",
    "deadline exceeded",
    "too many requests",
    "503",
    "504",
)

# Consecutive transport failures after which we stop trying for the session.
# A host with no outbound route would otherwise emit identical tracebacks all
# day and keep burning the daily write budget.
_MAX_CONSECUTIVE_TRANSPORT_FAILURES = 5


class FirebaseService:
    """Singleton wrapper around Firestore + Storage."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.enabled = FIREBASE_ENABLED and FIREBASE_AVAILABLE
        if not self.enabled:
            logger.info("Firebase is disabled or SDK not available")
            self.db = None
            self.bucket = None
            self._quota_exhausted = False
            self._transport_down = False
            self._consecutive_transport_failures = 0
            self._max_transport_retries = max(1, FIREBASE_MAX_TRANSPORT_RETRIES)
            self._retry_backoff = max(0.0, FIREBASE_RETRY_BACKOFF)
            return

        try:
            if not FIREBASE_CREDENTIALS_PATH or not os.path.exists(FIREBASE_CREDENTIALS_PATH):
                logger.warning(f"Firebase credentials not found at: {FIREBASE_CREDENTIALS_PATH}")
                self.enabled = False
                self.db = None
                self.bucket = None
                self._quota_exhausted = False
                self._transport_down = False
                self._consecutive_transport_failures = 0
                self._max_transport_retries = max(1, FIREBASE_MAX_TRANSPORT_RETRIES)
                self._retry_backoff = max(0.0, FIREBASE_RETRY_BACKOFF)
                return

            try:
                firebase_admin.get_app()
                logger.info("Firebase app already initialized")
            except ValueError:
                cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred, {
                    "databaseURL": FIREBASE_DATABASE_URL,
                    "storageBucket": FIREBASE_STORAGE_BUCKET,
                })
                logger.info("Firebase app initialized successfully")

            self.db = firestore.client()
            self.bucket = storage.bucket() if FIREBASE_STORAGE_BUCKET else None
            self.enabled = True
            self._quota_exhausted = False
            self._transport_down = False
            self._consecutive_transport_failures = 0
            self._max_transport_retries = max(1, FIREBASE_MAX_TRANSPORT_RETRIES)
            self._retry_backoff = max(0.0, FIREBASE_RETRY_BACKOFF)
            logger.info("Firebase service ready")

        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            self.enabled = False
            self.db = None
            self.bucket = None
            self._quota_exhausted = False
            self._transport_down = False
            self._consecutive_transport_failures = 0
            self._max_transport_retries = max(1, FIREBASE_MAX_TRANSPORT_RETRIES)
            self._retry_backoff = max(0.0, FIREBASE_RETRY_BACKOFF)

    def is_enabled(self) -> bool:
        return self.enabled and self.db is not None

    def _is_transient(self, exc: Exception) -> bool:
        """True for errors a retry has a real chance of fixing."""
        message = str(exc).lower()
        return any(marker in message for marker in _TRANSIENT_MARKERS)

    def _retrying(self, call, *args, **kwargs):
        """Run a blocking Firestore call, retrying transient transport errors.

        Raises whatever the call raised once the budget is spent; the
        caller's own ``except`` block decides what that means.
        """
        if self._transport_down:
            raise RuntimeError("Firebase transport marked down for this session")

        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_transport_retries + 1):
            try:
                result = call(*args, **kwargs)
            except Exception as exc:
                if not self._is_transient(exc):
                    raise
                last_error = exc
                self._consecutive_transport_failures += 1
                if self._consecutive_transport_failures >= _MAX_CONSECUTIVE_TRANSPORT_FAILURES:
                    self._transport_down = True
                    logger.error(
                        "Firebase unreachable after %d consecutive transport "
                        "failures — disabling sync for this session. Last error: %s",
                        self._consecutive_transport_failures, exc,
                    )
                    raise
                delay = self._retry_backoff * attempt
                logger.warning(
                    "Firebase transport error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, self._max_transport_retries, delay, exc,
                )
                if delay:
                    time.sleep(delay)
                continue
            self._consecutive_transport_failures = 0
            return result

        # Budget spent on the last transient error: re-raise that original
        # exception so the caller's handler sees the real cause, not a
        # synthetic "unreachable" RuntimeError.
        raise last_error

    def is_transport_down(self) -> bool:
        """True when the consecutive-failure breaker has tripped."""
        return getattr(self, "_transport_down", False)

    # ------------------------------------------------------------
    # SYNC METHODS — call from threads / asyncio.to_thread
    # ------------------------------------------------------------
    def save_reading(self, reading_data: Dict, user_id: int) -> bool:
        if not self.is_enabled():
            return False
        if self.is_transport_down():
            logger.debug("Firebase transport down; skipping write for this session")
            return False
        try:
            reading_id = reading_data.get("reading_id", f"reading_{datetime.now().timestamp()}")
            doc_ref = self.db.collection("readings").document(reading_id)
            reading_data["user_id"] = str(user_id)
            reading_data["reading_id"] = reading_id
            reading_data["timestamp"] = reading_data.get("timestamp", datetime.now().isoformat())
            reading_data["synced_at"] = firestore.SERVER_TIMESTAMP
            self._retrying(doc_ref.set, reading_data)
            logger.info(f"Reading {reading_id} saved to Firebase")
            return True
        except Exception as e:
            # Quota errors: surface clearly so the bot can stop trying for the
            # rest of the session — otherwise the auto-sync loop drains the
            # whole daily Spark budget in seconds.
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "gone over" in msg.lower() or "429" in msg:
                logger.warning(
                    f"Firebase daily quota exhausted — disabling further writes for this session. "
                    f"Error: {e}"
                )
                self._quota_exhausted = True
            else:
                logger.error(f"Failed to save reading to Firebase: {e}")
            return False

    def save_reading_if_absent(self, reading_data: Dict, user_id: int) -> str:
        """Skip the write if the document already exists.

        Returns one of:
          - ``"created"`` — wrote a new document
          - ``"exists"``  — doc already present, skipped (no write charged)
          - ``"quota"``   — quota exhausted, disabled for this session
          - ``"error"``   — other failure (logged)
        """
        if not self.is_enabled():
            return "error"
        if self.is_transport_down():
            logger.debug("Firebase transport down; skipping write for this session")
            return "error"
        if getattr(self, "_quota_exhausted", False):
            return "quota"
        try:
            reading_id = reading_data.get("reading_id", f"reading_{datetime.now().timestamp()}")
            doc_ref = self.db.collection("readings").document(reading_id)
            # Cheap point-read; counts against the 50K/day read budget.
            if self._retrying(doc_ref.get).exists:
                logger.debug(f"Reading {reading_id} already in Firebase, skipping")
                return "exists"
            reading_data["user_id"] = str(user_id)
            reading_data["reading_id"] = reading_id
            reading_data["timestamp"] = reading_data.get("timestamp", datetime.now().isoformat())
            reading_data["synced_at"] = firestore.SERVER_TIMESTAMP
            self._retrying(doc_ref.set, reading_data)
            logger.info(f"Reading {reading_id} saved to Firebase (idempotent)")
            return "created"
        except Exception as e:
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "gone over" in msg.lower() or "429" in msg:
                logger.warning(
                    f"Firebase daily quota exhausted during idempotent write — "
                    f"disabling further writes. Error: {e}"
                )
                self._quota_exhausted = True
                return "quota"
            logger.error(f"Failed to save reading (idempotent) to Firebase: {e}")
            return "error"


    def save_user_settings(self, user_id: int, settings: Dict) -> bool:
        if not self.is_enabled():
            return False
        try:
            doc_ref = self.db.collection("users").document(str(user_id))
            doc_ref.set({
                "user_id": user_id,
                "settings": settings,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            logger.info(f"User settings saved for {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save user settings: {e}")
            return False

    def get_user_readings(self, user_id: int, limit: int = 50) -> List[Dict]:
        if not self.is_enabled():
            return []
        try:
            docs = (self.db.collection("readings")
                    .where("user_id", "==", str(user_id))
                    .order_by("timestamp", direction=firestore.Query.DESCENDING)
                    .limit(limit)
                    .get())
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get user readings: {e}")
            return []

    def get_all_user_readings(self, user_id: int) -> List[Dict]:
        if not self.is_enabled():
            return []
        try:
            docs = (self.db.collection("readings")
                    .where("user_id", "==", str(user_id))
                    .order_by("timestamp", direction=firestore.Query.DESCENDING)
                    .get())
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get all user readings: {e}")
            return []

    def save_card_statistics(self, stats: Dict) -> bool:
        if not self.is_enabled():
            return False
        try:
            doc_ref = self.db.collection("statistics").document("card_stats")
            doc_ref.set({
                "stats": stats,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            return True
        except Exception as e:
            logger.error(f"Failed to save card statistics: {e}")
            return False

    def save_journal_entry(self, user_id: int, entry: Dict) -> bool:
        if not self.is_enabled():
            return False
        try:
            doc_ref = self.db.collection("journals").document(f"user_{user_id}")
            doc = doc_ref.get()
            if doc.exists:
                entries = doc.to_dict().get("entries", [])
            else:
                entries = []
            entry["created_at"] = datetime.now().isoformat()
            entries.append(entry)
            doc_ref.set({
                "user_id": user_id,
                "entries": entries,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            logger.info(f"Journal entry saved for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save journal: {e}")
            return False

    def get_journal_entries(self, user_id: int) -> List[Dict]:
        if not self.is_enabled():
            return []
        try:
            doc_ref = self.db.collection("journals").document(f"user_{user_id}")
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict().get("entries", [])
            return []
        except Exception as e:
            logger.error(f"Failed to get journal: {e}")
            return []

    def delete_user_data(self, user_id: int) -> bool:
        if not self.is_enabled():
            return False
        try:
            docs = (self.db.collection("readings")
                    .where("user_id", "==", str(user_id))
                    .get())
            for doc in docs:
                doc.reference.delete()
            self.db.collection("journals").document(f"user_{user_id}").delete()
            logger.info(f"All data for user {user_id} deleted from Firebase")
            return True
        except Exception as e:
            logger.error(f"Failed to delete user data: {e}")
            return False

    def sync_local_to_firebase(self, local_data: Dict) -> bool:
        if not self.is_enabled():
            return False
        try:
            readings = local_data.get("readings", [])
            for reading in readings:
                user_id = int(reading.get("user_id", 0))
                if user_id:
                    self.save_reading(reading, user_id)
            logger.info(f"Synced {len(readings)} readings to Firebase")
            return True
        except Exception as e:
            logger.error(f"Failed to sync data: {e}")
            return False

    # ------------------------------------------------------------
    # ASYNC WRAPPERS — safe to await from command code.
    # ------------------------------------------------------------
    async def async_save_reading(self, reading_data: Dict, user_id: int) -> bool:
        return await asyncio.to_thread(self.save_reading, reading_data, user_id)

    async def async_save_reading_if_absent(self, reading_data: Dict, user_id: int) -> str:
        return await asyncio.to_thread(self.save_reading_if_absent, reading_data, user_id)

    async def async_save_user_settings(self, user_id: int, settings: Dict) -> bool:
        return await asyncio.to_thread(self.save_user_settings, user_id, settings)

    async def async_get_user_readings(self, user_id: int, limit: int = 50) -> List[Dict]:
        return await asyncio.to_thread(self.get_user_readings, user_id, limit)

    async def async_get_all_user_readings(self, user_id: int) -> List[Dict]:
        return await asyncio.to_thread(self.get_all_user_readings, user_id)

    async def async_save_card_statistics(self, stats: Dict) -> bool:
        return await asyncio.to_thread(self.save_card_statistics, stats)

    async def async_save_journal_entry(self, user_id: int, entry: Dict) -> bool:
        return await asyncio.to_thread(self.save_journal_entry, user_id, entry)

    async def async_get_journal_entries(self, user_id: int) -> List[Dict]:
        return await asyncio.to_thread(self.get_journal_entries, user_id)

    async def async_delete_user_data(self, user_id: int) -> bool:
        return await asyncio.to_thread(self.delete_user_data, user_id)

    async def async_sync_local_to_firebase(self, local_data: Dict) -> bool:
        return await asyncio.to_thread(self.sync_local_to_firebase, local_data)


firebase_service = FirebaseService()
