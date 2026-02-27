import base64
import json
import platform
from pathlib import Path


class SecretStoreError(RuntimeError):
    pass


def _windows_decrypt(cipher_text: bytes) -> bytes:
    try:
        import win32crypt  # type: ignore
    except ImportError as exc:
        raise SecretStoreError('Windows 环境缺少 pywin32，无法解密 DPAPI 文件') from exc

    return win32crypt.CryptUnprotectData(cipher_text, None, None, None, 0)[1]


def _windows_encrypt(plain_text: bytes) -> bytes:
    try:
        import win32crypt  # type: ignore
    except ImportError as exc:
        raise SecretStoreError('Windows 环境缺少 pywin32，无法加密 DPAPI 文件') from exc

    return win32crypt.CryptProtectData(plain_text, None, None, None, None, 0)


def load_secret_file(path: Path) -> dict:
    if not path.exists():
        return {}

    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8'))
    if data.get('mode') == 'dpapi':
        if platform.system() != 'Windows':
            raise SecretStoreError('仅 Windows 支持 dpapi 模式')
        plain = _windows_decrypt(base64.b64decode(data['payload']))
        return json.loads(plain.decode('utf-8'))

    if data.get('mode') == 'plain':
        return data.get('payload', {})

    raise SecretStoreError('未知 secret 文件格式')


def save_secret_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == 'Windows':
        cipher = _windows_encrypt(json.dumps(payload).encode('utf-8'))
        content = {'mode': 'dpapi', 'payload': base64.b64encode(cipher).decode('utf-8')}
    else:
        # 非 Windows 开发调试回退到明文模式，生产请在 Windows 上生成。
        content = {'mode': 'plain', 'payload': payload}

    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
