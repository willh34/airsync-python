import os
import base64
import logging
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

class AESSipher:
    """
    Handles all AES-256-GCM encryption, decryption, and key management.
    """
    def __init__(self, key_path="airsync.key"):
        self.key_path = key_path
        self.key = self._load_key()
        logging.debug("AESSipher initialized.")

    def _load_key(self):
        """Loads key from file, or generates a new one."""
        try:
            if os.path.exists(self.key_path):
                logging.debug(f"Loading existing key from {self.key_path}")
                with open(self.key_path, "rb") as f:
                    return f.read()
            
            logging.info(f"No key found. Generating new key at {self.key_path}")
            key = AESGCM.generate_key(bit_length=256)
            with open(self.key_path, "wb") as f:
                f.write(key)
            return key
        except Exception as e:
            logging.critical(f"Failed to load or write key file at {self.key_path}: {e}", exc_info=True)
            raise

    def get_key_base64(self) -> str:
        """Returns the current key as a Base64 string."""
        return base64.b64encode(self.key).decode()

    def encrypt_message(self, message: str) -> str:
        """Encrypts a plaintext string using AES-256-GCM."""
        try:
            nonce = os.urandom(12) # 96-bit nonce
            cipher = AESGCM(self.key)
            ciphertext = cipher.encrypt(nonce, message.encode('utf-8'), None)
            # Prepend nonce to ciphertext as per docs
            return base64.b64encode(nonce + ciphertext).decode()
        except Exception as e:
            logging.error(f"Encryption failed: {e}", exc_info=True)
            return ""

    def decrypt_message(self, encrypted_base64: str) -> str:
        """Decrypts a Base64 string using AES-256-GCM."""
        try:
            combined = base64.b64decode(encrypted_base64)
            nonce = combined[:12]
            ciphertext = combined[12:]
            cipher = AESGCM(self.key)
            plaintext = cipher.decrypt(nonce, ciphertext, None)
            return plaintext.decode('utf-8')
        except (InvalidTag, Exception) as e:
            # If decryption fails, it might be a client connecting with no-encrypt.
            # Return the raw string for the JSON parser to handle.
            logging.warning(f"Decryption failed (InvalidTag or other error). Is client using encryption?")
            return encrypted_base64

