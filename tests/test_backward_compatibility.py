"""
Unit tests for backward compatibility of renamed exception classes.

Tests that the old exception names from before commit fdd69b1 still work
to maintain compatibility with external projects like targetd.
"""

import pytest


class TestBackwardCompatibility:
    """Test backward compatibility for renamed exception classes."""

    def test_old_exception_names_exist(self):
        """Test that old exception names are still available in rtslib module."""
        import rtslib

        # Test that old names exist
        assert hasattr(rtslib, 'RTSLibALUANotSupported')
        assert hasattr(rtslib, 'RTSLibNotInCFS')

    def test_new_exception_names_exist(self):
        """Test that new PEP8-compliant exception names exist."""
        import rtslib

        # Test that new names exist
        assert hasattr(rtslib, 'RTSLibALUANotSupportedError')
        assert hasattr(rtslib, 'RTSLibNotInCFSError')

    def test_exception_aliases_point_to_same_class(self):
        """Test that old and new names refer to the same classes."""
        import rtslib

        assert rtslib.RTSLibALUANotSupported is rtslib.RTSLibALUANotSupportedError
        assert rtslib.RTSLibNotInCFS is rtslib.RTSLibNotInCFSError

    def test_aliases_in_module_all(self):
        """Test that both old and new names are exported in __all__."""
        import rtslib

        assert 'RTSLibALUANotSupported' in rtslib.__all__
        assert 'RTSLibNotInCFS' in rtslib.__all__
        assert 'RTSLibALUANotSupportedError' in rtslib.__all__
        assert 'RTSLibNotInCFSError' in rtslib.__all__

    def test_exception_inheritance(self):
        """Test that all exceptions inherit from RTSLibError."""
        import rtslib

        assert issubclass(rtslib.RTSLibALUANotSupported, rtslib.RTSLibError)
        assert issubclass(rtslib.RTSLibNotInCFS, rtslib.RTSLibError)
        assert issubclass(rtslib.RTSLibALUANotSupportedError, rtslib.RTSLibError)
        assert issubclass(rtslib.RTSLibNotInCFSError, rtslib.RTSLibError)

    def test_raise_and_catch_old_alua_exception(self):
        """Test raising and catching RTSLibALUANotSupported."""
        import rtslib

        with pytest.raises(rtslib.RTSLibALUANotSupported):
            raise rtslib.RTSLibALUANotSupported("Test ALUA exception")

    def test_raise_and_catch_old_cfs_exception(self):
        """Test raising and catching RTSLibNotInCFS."""
        import rtslib

        with pytest.raises(rtslib.RTSLibNotInCFS):
            raise rtslib.RTSLibNotInCFS("Test CFS exception")

    def test_cross_compatibility_alua_exception(self):
        """Test that new exception can be caught with old name."""
        import rtslib

        with pytest.raises(rtslib.RTSLibALUANotSupported):
            raise rtslib.RTSLibALUANotSupportedError("Test exception")

    def test_cross_compatibility_cfs_exception(self):
        """Test that new exception can be caught with old name."""
        import rtslib

        with pytest.raises(rtslib.RTSLibNotInCFS):
            raise rtslib.RTSLibNotInCFSError("Test exception")

    def test_old_exception_can_be_caught_with_new_name(self):
        """Test that old exception name can be caught with new name."""
        import rtslib

        with pytest.raises(rtslib.RTSLibALUANotSupportedError):
            raise rtslib.RTSLibALUANotSupported("Test exception")

        with pytest.raises(rtslib.RTSLibNotInCFSError):
            raise rtslib.RTSLibNotInCFS("Test exception")

    def test_exception_messages_preserved(self):
        """Test that exception messages work correctly with both names."""
        import rtslib

        test_message = "Custom error message"

        try:
            raise rtslib.RTSLibALUANotSupported(test_message)
        except rtslib.RTSLibALUANotSupportedError as e:
            assert str(e) == test_message

        try:
            raise rtslib.RTSLibNotInCFS(test_message)
        except rtslib.RTSLibNotInCFSError as e:
            assert str(e) == test_message
