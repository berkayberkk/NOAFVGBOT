"""Unit tests for forex_daytrade.domain.validation."""

from forex_daytrade.domain.validation import Severity, ValidationIssue, ValidationReport


def test_empty_report_is_valid() -> None:
    report = ValidationReport()
    assert report.is_valid
    assert report.errors == ()
    assert report.warnings == ()
    assert dict(report.statistics) == {}


def test_report_with_only_warnings_is_valid() -> None:
    issue = ValidationIssue(check="gap", severity=Severity.WARNING, message="gap found")
    report = ValidationReport(issues=(issue,))
    assert report.is_valid
    assert report.warnings == (issue,)
    assert report.errors == ()


def test_report_with_error_is_invalid() -> None:
    issue = ValidationIssue(check="dupes", severity=Severity.ERROR, message="duplicate rows")
    report = ValidationReport(issues=(issue,))
    assert not report.is_valid
    assert report.errors == (issue,)


def test_report_separates_errors_and_warnings() -> None:
    warning = ValidationIssue(check="gap", severity=Severity.WARNING, message="gap")
    error = ValidationIssue(check="dupes", severity=Severity.ERROR, message="dupes")
    report = ValidationReport(issues=(warning, error))
    assert report.errors == (error,)
    assert report.warnings == (warning,)


def test_statistics_are_preserved() -> None:
    report = ValidationReport(statistics={"row_count": 100})
    assert report.statistics["row_count"] == 100


def test_severity_values() -> None:
    assert Severity.WARNING.value == "warning"
    assert Severity.ERROR.value == "error"


def test_issue_equality() -> None:
    issue_a = ValidationIssue(check="dupes", severity=Severity.ERROR, message="x")
    issue_b = ValidationIssue(check="dupes", severity=Severity.ERROR, message="x")
    assert issue_a == issue_b


def test_report_equality() -> None:
    assert ValidationReport() == ValidationReport()
