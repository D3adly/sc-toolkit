"""app.aes against the published test vectors."""

import unittest

from app import aes


class AesTest(unittest.TestCase):
    def test_fips197_block(self):
        # FIPS-197 appendix C.1: decrypting the ciphertext gives the plaintext back (CBC with a zero IV = ECB for one block).
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual("00112233445566778899aabbccddeeff", aes.decrypt_cbc(key, cipher).hex())

    def test_sp800_38a_cbc(self):
        # NIST SP 800-38A F.2.2, CBC-AES128.Decrypt, all four blocks.
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        cipher = bytes.fromhex("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"
                               "73bed6b8e3c1743b7116e69e222295163ff1caa1681fac09120eca307586e1a7")
        plain = ("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
                 "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710")
        self.assertEqual(plain, aes.decrypt_cbc(key, cipher, iv).hex())

    def test_rejects_partial_blocks(self):
        with self.assertRaises(ValueError):
            aes.decrypt_cbc(bytes(16), bytes(15))


if __name__ == "__main__":
    unittest.main()
