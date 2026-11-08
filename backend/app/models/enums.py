"""Domain enumerations (Section 7.2). Stored as VARCHAR with CHECK constraints."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    QUALITY_HEAD = "QUALITY_HEAD"
    SUPERVISOR = "SUPERVISOR"
    PROCESS_OWNER = "PROCESS_OWNER"
    INSPECTOR = "INSPECTOR"
    VIEWER = "VIEWER"


class CmmVendor(StrEnum):
    ZEISS_CALYPSO = "ZEISS_CALYPSO"
    HEXAGON_PCDMIS = "HEXAGON_PCDMIS"
    OTHER = "OTHER"


class CharKind(StrEnum):
    DIMENSION = "DIMENSION"
    GEOMETRIC = "GEOMETRIC"


class ToleranceType(StrEnum):
    BILATERAL = "BILATERAL"
    UPPER_ONLY = "UPPER_ONLY"
    LOWER_ONLY = "LOWER_ONLY"


class CharClass(StrEnum):
    CRITICAL = "CRITICAL"
    SIGNIFICANT = "SIGNIFICANT"
    STANDARD = "STANDARD"


class FileKind(StrEnum):
    CSV = "CSV"
    XLSX = "XLSX"
    TSV = "TSV"
    CALYPSO_CHR = "CALYPSO_CHR"
    AQDEF = "AQDEF"
    PDF = "PDF"


class ReportSource(StrEnum):
    UPLOAD = "UPLOAD"
    WATCH_FOLDER = "WATCH_FOLDER"
    MANUAL = "MANUAL"
    AI_PDF = "AI_PDF"


class Result(StrEnum):
    OK = "OK"
    MARGINAL = "MARGINAL"
    NOK = "NOK"


class ReportStatus(StrEnum):
    INGESTED = "INGESTED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    FAILED = "FAILED"


class LimitsSource(StrEnum):
    MASTER = "MASTER"
    REPORT = "REPORT"


class NcStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RootCauseCategory(StrEnum):
    MAN = "MAN"
    MACHINE = "MACHINE"
    METHOD = "METHOD"
    MATERIAL = "MATERIAL"
    MEASUREMENT = "MEASUREMENT"
    ENVIRONMENT = "ENVIRONMENT"


class AlertKind(StrEnum):
    NOK = "NOK"
    RECURRENCE = "RECURRENCE"
    ESCALATION = "ESCALATION"
    SPC_WARNING = "SPC_WARNING"
    SYSTEM = "SYSTEM"


class OutboxKind(StrEnum):
    EMAIL = "EMAIL"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class SpcSignalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLEARED = "CLEARED"
