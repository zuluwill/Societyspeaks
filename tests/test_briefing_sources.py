"""
Regression tests for template-based briefing source population.
Tests the populate_briefing_sources_from_template utility function.
"""

import pytest


class TestPopulateBriefingSourcesEdgeCases:
    """Tests for edge cases in populate_briefing_sources_from_template utility."""

    def test_empty_sources_returns_zeros(self, app_context):
        """Empty default_sources should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, None, mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []

    def test_empty_list_returns_zeros(self, app_context):
        """Empty list should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, [], mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []

    def test_non_list_returns_zeros(self, app_context):
        """Non-list default_sources should return 0 added, 0 failed."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        added, failed, missing = populate_briefing_sources_from_template(
            mock_briefing, "not a list", mock_user
        )
        
        assert added == 0
        assert failed == 0
        assert missing == []


class TestTransactionSafety:
    """Tests for transaction atomicity."""

    def test_create_input_source_uses_flush(self, app_context):
        """create_input_source_from_news_source should use flush, not commit."""
        import inspect
        from app.briefing.routes import create_input_source_from_news_source
        
        source_code = inspect.getsource(create_input_source_from_news_source)
        
        assert 'db.session.flush()' in source_code
        assert 'db.session.commit()' not in source_code


class TestUtilityFunctionExists:
    """Tests to verify utility function is properly defined."""

    def test_populate_briefing_sources_function_exists(self, app_context):
        """Utility function should be importable."""
        from app.briefing.routes import populate_briefing_sources_from_template
        
        assert callable(populate_briefing_sources_from_template)

    def test_function_returns_three_values(self, app_context):
        """Function should return tuple of (added, failed, missing)."""
        from unittest.mock import Mock
        from app.briefing.routes import populate_briefing_sources_from_template
        
        result = populate_briefing_sources_from_template(Mock(), None, Mock())
        
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_function_docstring_exists(self, app_context):
        """Function should have documentation."""
        from app.briefing.routes import populate_briefing_sources_from_template
        
        assert populate_briefing_sources_from_template.__doc__ is not None
        assert 'source' in populate_briefing_sources_from_template.__doc__.lower()


class TestSourceFormatHandling:
    """Tests for source format handling logic via code inspection."""

    def test_handles_dict_format(self, app_context):
        """Function should handle dict format sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, dict)" in source_code
        assert "source_ref.get('name')" in source_code

    def test_handles_int_format(self, app_context):
        """Function should handle integer ID sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, int)" in source_code

    def test_handles_string_format(self, app_context):
        """Function should handle string name sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "isinstance(source_ref, str)" in source_code

    def test_has_case_insensitive_fallback(self, app_context):
        """Function should have case-insensitive lookup fallback."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "db.func.lower" in source_code
        assert ".lower()" in source_code


class TestLoggingBehavior:
    """Tests for logging configuration."""

    def test_logs_missing_sources(self, app_context):
        """Function should log warnings for missing sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "logger.warning" in source_code
        assert "NewsSource not found" in source_code

    def test_logs_missing_sources_summary(self, app_context):
        """Function should log summary of missing sources."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "missing_sources" in source_code
        assert "sources not found in database" in source_code


class TestDuplicateProtection:
    """Tests for duplicate source protection."""

    def test_checks_existing_briefing_source(self, app_context):
        """Function should check for existing BriefingSource before adding."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "BriefingSource.query.filter_by" in source_code
        assert "briefing_id=briefing.id" in source_code
        assert "source_id=source.id" in source_code


class TestAccessControl:
    """Tests for access control."""

    def test_checks_source_access(self, app_context):
        """Function should verify user can access source."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "can_access_source" in source_code


class TestBehavioralSourcePopulation:
    """Behavioral tests using mocks to exercise function logic."""

    def test_missing_news_source_tracked_in_results(self, app_context):
        """When NewsSource not found, it should be added to missing list."""
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class:
            mock_ns_class.query.filter_by.return_value.first.return_value = None
            mock_ns_class.query.filter.return_value.first.return_value = None
            
            sources = [{'name': 'NonExistent Source', 'type': 'rss'}]
            
            added, failed, missing = populate_briefing_sources_from_template(
                mock_briefing, sources, mock_user
            )
            
            assert added == 0
            assert failed == 0
            assert 'NonExistent Source' in missing

    def test_access_denied_handled(self, app_context):
        """Function should check access via can_access_source."""
        import inspect
        from app.briefing.routes import populate_briefing_sources_from_template
        
        source_code = inspect.getsource(populate_briefing_sources_from_template)
        
        assert "can_access_source(user, source)" in source_code
        assert "sources_failed += 1" in source_code

    def test_duplicate_source_not_readded(self, app_context):
        """When BriefingSource already exists, it should not be added again."""
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class, \
             patch('app.briefing.routes.BriefingSource') as mock_bs_class, \
             patch('app.briefing.routes.create_input_source_from_news_source') as mock_create, \
             patch('app.briefing.routes.can_access_source') as mock_access, \
             patch('app.briefing.routes.db'):
            
            mock_ns = Mock()
            mock_ns.id = 10
            mock_ns_class.query.filter_by.return_value.first.return_value = mock_ns
            
            mock_input = Mock()
            mock_input.id = 100
            mock_create.return_value = mock_input
            
            mock_access.return_value = True
            
            existing_bs = Mock()
            mock_bs_class.query.filter_by.return_value.first.return_value = existing_bs
            
            sources = [{'name': 'Duplicate Source', 'type': 'rss'}]
            
            added, failed, missing = populate_briefing_sources_from_template(
                mock_briefing, sources, mock_user
            )
            
            assert added == 0
            mock_bs_class.query.filter_by.assert_called()

    def test_successful_source_addition(self, app_context):
        """When source is found and accessible, it should be added."""
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class, \
             patch('app.briefing.routes.BriefingSource') as mock_bs_class, \
             patch('app.briefing.routes.create_input_source_from_news_source') as mock_create, \
             patch('app.briefing.routes.can_access_source') as mock_access, \
             patch('app.briefing.routes.db') as mock_db:
            
            mock_ns = Mock()
            mock_ns.id = 10
            mock_ns_class.query.filter_by.return_value.first.return_value = mock_ns
            
            mock_input = Mock()
            mock_input.id = 100
            mock_create.return_value = mock_input
            
            mock_access.return_value = True
            mock_bs_class.query.filter_by.return_value.first.return_value = None
            
            sources = [{'name': 'Valid Source', 'type': 'rss'}]
            
            added, failed, missing = populate_briefing_sources_from_template(
                mock_briefing, sources, mock_user
            )
            
            assert added == 1
            assert failed == 0
            assert missing == []
            mock_db.session.add.assert_called()

    def test_case_insensitive_fallback_used(self, app_context):
        """When exact match fails, case-insensitive lookup should be tried."""
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class, \
             patch('app.briefing.routes.BriefingSource') as mock_bs_class, \
             patch('app.briefing.routes.create_input_source_from_news_source') as mock_create, \
             patch('app.briefing.routes.can_access_source') as mock_access, \
             patch('app.briefing.routes.db') as mock_db:
            
            mock_ns_class.query.filter_by.return_value.first.return_value = None
            
            mock_ns = Mock()
            mock_ns.id = 10
            mock_ns_class.query.filter.return_value.first.return_value = mock_ns
            
            mock_input = Mock()
            mock_input.id = 100
            mock_create.return_value = mock_input
            
            mock_access.return_value = True
            mock_bs_class.query.filter_by.return_value.first.return_value = None
            
            sources = [{'name': 'BBC NEWS', 'type': 'rss'}]
            
            added, failed, missing = populate_briefing_sources_from_template(
                mock_briefing, sources, mock_user
            )
            
            assert added == 1
            mock_ns_class.query.filter.assert_called()


class TestLoggingVerification:
    """Tests that verify logging actually fires."""

    def test_missing_source_logs_warning(self, app_context, caplog):
        """When source is not found, a warning should be logged."""
        import logging
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class:
            mock_ns_class.query.filter_by.return_value.first.return_value = None
            mock_ns_class.query.filter.return_value.first.return_value = None
            
            sources = [{'name': 'Missing Source', 'type': 'rss'}]
            
            with caplog.at_level(logging.WARNING):
                added, failed, missing = populate_briefing_sources_from_template(
                    mock_briefing, sources, mock_user
                )
            
            assert 'Missing Source' in missing
            assert any('NewsSource not found' in record.message for record in caplog.records)

    def test_missing_sources_summary_logged(self, app_context, caplog):
        """Summary warning should be logged when sources are missing."""
        import logging
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class:
            mock_ns_class.query.filter_by.return_value.first.return_value = None
            mock_ns_class.query.filter.return_value.first.return_value = None
            
            sources = [
                {'name': 'Source 1', 'type': 'rss'},
                {'name': 'Source 2', 'type': 'rss'}
            ]
            
            with caplog.at_level(logging.WARNING):
                added, failed, missing = populate_briefing_sources_from_template(
                    mock_briefing, sources, mock_user
                )
            
            assert len(missing) == 2
            assert any('sources not found in database' in record.message for record in caplog.records)


class TestEdgeCasesBehavioral:
    """Behavioral tests for edge cases."""

    def test_multiple_sources_mixed_results(self, app_context):
        """Mix of found and missing sources should be handled correctly."""
        from unittest.mock import Mock, patch
        from app.briefing.routes import populate_briefing_sources_from_template
        
        mock_briefing = Mock()
        mock_briefing.id = 1
        mock_user = Mock()
        
        with patch('app.briefing.routes.NewsSource') as mock_ns_class, \
             patch('app.briefing.routes.BriefingSource') as mock_bs_class, \
             patch('app.briefing.routes.create_input_source_from_news_source') as mock_create, \
             patch('app.briefing.routes.can_access_source') as mock_access, \
             patch('app.briefing.routes.db') as mock_db:
            
            mock_ns = Mock()
            mock_ns.id = 10
            
            def filter_by_side_effect(**kwargs):
                result = Mock()
                if kwargs.get('name') == 'Found Source':
                    result.first.return_value = mock_ns
                else:
                    result.first.return_value = None
                return result
            
            mock_ns_class.query.filter_by.side_effect = filter_by_side_effect
            mock_ns_class.query.filter.return_value.first.return_value = None
            
            mock_input = Mock()
            mock_input.id = 100
            mock_create.return_value = mock_input
            
            mock_access.return_value = True
            mock_bs_class.query.filter_by.return_value.first.return_value = None
            
            sources = [
                {'name': 'Found Source', 'type': 'rss'},
                {'name': 'Missing Source', 'type': 'rss'}
            ]
            
            added, failed, missing = populate_briefing_sources_from_template(
                mock_briefing, sources, mock_user
            )
            
            assert added == 1
            assert 'Missing Source' in missing
