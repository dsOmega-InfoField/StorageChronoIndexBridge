import pytest
from unittest.mock import MagicMock, patch
import json
from pathlib import Path
from symlink_manager.main import SymlinkManager

@pytest.fixture
def mock_manager():
    """Create a SymlinkManager with mocked dependencies."""
    with patch('symlink_manager.plyvel.DB'), \
         patch('symlink_manager.Path'), \
         patch('symlink_manager.os') as mock_os, \
         patch('symlink_manager.platform.system') as mock_system:
        
        mock_system.return_value = 'Linux'
        mock_os.path.exists.return_value = True
        mock_os.readlink.return_value = '/original/path'
        
        manager = SymlinkManager('/mock/repo')
        manager.db = MagicMock()
        manager.repo_path = Path('/mock/repo')
        manager.gitignore_spec = MagicMock()
        
        yield manager

# def test_add_symlink(mock_manager):
#     """Test adding a new symlink with mocked dependencies."""
#     mock_manager._get_relative_path.return_value = 'relative/link'
#     mock_manager._is_ignored.return_value = False
#     
#     result = mock_manager.add_symlink('link', '/target/path')
#     
#     assert result == 'relative/link'
#     mock_manager._is_ignored.assert_called_once()
#     mock_manager.db.put.assert_called_once_with(
#         b'relative/link',
#         json.dumps({
#             'original_target': '/target/path',
#             'translations': {'linux': '/target/path'}
#         }).encode()
#     )

# def test_remove_symlink(mock_manager):
#     """Test removing a symlink with mocked dependencies."""
#     mock_manager._get_relative_path.return_value = 'relative/link'
#     mock_manager._is_ignored.return_value = False
#     
#     result = mock_manager.remove_symlink('link')
#     
#     assert result == 'relative/link'
#     mock_manager.db.delete.assert_called_once_with(b'relative/link')

# def test_missing_target_cleanup(mock_manager):
#     """Test cleanup when target is missing."""
#     # Setup mock DB iterator
#     mock_manager.db.return_value = [(b'valid_link', json.dumps({
#         'original_target': '/exists',
#         'translations': {}
#     }).encode()), (b'missing_link', json.dumps({
#         'original_target': '/missing',
#         'translations': {}
#     }).encode())]
#     
#     # Mock filesystem responses
#     def mock_exists(path):
#         return str(path) != '/mock/repo/missing_link'
#     
#     mock_manager.repo_path.__truediv__.side_effect = lambda x: Path(f'/mock/repo/{x}')
#     mock_manager._is_ignored.return_value = False
#     with patch('symlink_manager.os.path.exists', side_effect=mock_exists):
#         deleted = mock_manager.cleanup_deleted_symlinks()
#     
#     assert deleted == 1
#     mock_manager.db.delete.assert_called_once_with(b'missing_link')

# def test_renamed_target_update(mock_manager):
#     """Test updating when target is renamed."""
#     mock_manager._get_relative_path.return_value = 'relative/link'
#     mock_manager.db.get.return_value = json.dumps({
#         'original_target': '/old/path',
#         'translations': {'linux': '/old/path'}
#     }).encode()
#     
#     result = mock_manager.update_symlink_target('link', '/new/path')
#     
#     assert result == 'relative/link'
#     mock_manager.db.put.assert_called_once_with(
#         b'relative/link',
#         json.dumps({
#             'original_target': '/new/path',
#             'translations': {'linux': '/new/path'}
#         }).encode()
#     )

# def test_gitignore_respect(mock_manager):
#     """Test that ignored paths are properly handled."""
#     mock_manager.gitignore_spec.match_file.return_value = True
#     
#     untracked = mock_manager.scan_for_untracked_symlinks()
#     
#     assert untracked == []
#     mock_manager.gitignore_spec.match_file.assert_called()

# def test_platform_translation(mock_manager):
#     """Test cross-platform translation logic."""
#     mock_manager.current_os = 'windows'
#     mock_manager.translation_rules = {
#         'windows': {'/home/user': 'C:\\Users\\user'}
#     }
#     
#     translated = mock_manager.translate_path('/home/user/file.txt')
#     
#     assert translated == 'C:\\Users\\user\\file.txt'

# def test_full_sync(mock_manager):
#     """Test complete synchronization."""
#     # Mock scan_for_untracked_symlinks to return one new symlink
#     mock_manager.scan_for_untracked_symlinks.return_value = ['new_link']
#     mock_manager.process_all.return_value = 2
#     mock_manager.cleanup_deleted_symlinks.return_value = 1
#     
#     # Mock DB get for the new link
#     mock_manager.db.get.return_value = None
#     
#     result = mock_manager.full_sync()
#     
#     assert result == {'added': 1, 'updated': 2, 'deleted': 1}
#     mock_manager.db.put.assert_called_once()

# def test_symlink_info(mock_manager):
#     """Test getting symlink information."""
#     test_data = {
#         'original_target': '/original',
#         'translations': {'linux': '/linux/path'}
#     }
#     mock_manager.db.get.return_value = json.dumps(test_data).encode()
#     mock_manager._get_relative_path.return_value = 'test_link'
#     
#     info = mock_manager.get_symlink_info('link')
#     
#     assert info == test_data
#     mock_manager.db.get.assert_called_once_with(b'test_link')

# def test_list_symlinks(mock_manager):
#     """Test listing all tracked symlinks."""
#     mock_manager.db.return_value = [(b'link1', b'data1'), (b'link2', b'data2')]
#     
#     symlinks = mock_manager.list_symlinks()
#     
#     assert symlinks == ['link1', 'link2']
