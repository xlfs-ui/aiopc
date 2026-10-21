"""Generate small raster verification images without an image dependency."""
import base64
import secrets
import struct
import zlib

GLYPHS = {
 '2':'01110/10001/00001/00010/00100/01000/11111', '3':'11110/00001/00001/01110/00001/00001/11110',
 '4':'00010/00110/01010/10010/11111/00010/00010', '5':'11111/10000/10000/11110/00001/00001/11110',
 '6':'01110/10000/10000/11110/10001/10001/01110', '7':'11111/00001/00010/00100/01000/01000/01000',
 '8':'01110/10001/10001/01110/10001/10001/01110', '9':'01110/10001/10001/01111/00001/00001/01110',
 'A':'01110/10001/10001/11111/10001/10001/10001','B':'11110/10001/10001/11110/10001/10001/11110',
 'C':'01111/10000/10000/10000/10000/10000/01111','D':'11110/10001/10001/10001/10001/10001/11110',
 'E':'11111/10000/10000/11110/10000/10000/11111','F':'11111/10000/10000/11110/10000/10000/10000',
 'G':'01111/10000/10000/10111/10001/10001/01111','H':'10001/10001/10001/11111/10001/10001/10001',
 'J':'00111/00010/00010/00010/10010/10010/01100','K':'10001/10010/10100/11000/10100/10010/10001',
 'M':'10001/11011/10101/10101/10001/10001/10001','N':'10001/11001/10101/10011/10001/10001/10001',
 'P':'11110/10001/10001/11110/10000/10000/10000','R':'11110/10001/10001/11110/10100/10010/10001',
 'S':'01111/10000/10000/01110/00001/00001/11110','T':'11111/00100/00100/00100/00100/00100/00100',
 'U':'10001/10001/10001/10001/10001/10001/01110','V':'10001/10001/10001/10001/10001/01010/00100',
 'W':'10001/10001/10001/10101/10101/10101/01010','X':'10001/10001/01010/00100/01010/10001/10001',
 'Y':'10001/10001/01010/00100/00100/00100/00100','Z':'11111/00001/00010/00100/01000/10000/11111',
}


def generate():
    code = ''.join(secrets.choice(tuple(GLYPHS)) for _ in range(5))
    width, height = 180, 56
    pixels = bytearray([244, 248, 241] * width * height)
    def dot(x,y,color):
        if 0 <= x < width and 0 <= y < height:
            offset = (y*width+x)*3
            pixels[offset:offset+3] = bytes(color)
    for _ in range(400):
        dot(secrets.randbelow(width), secrets.randbelow(height), (181,199,183))
    for i,char in enumerate(code):
        x0, y0 = 12+i*33+secrets.randbelow(3), 9+secrets.randbelow(9)
        color = (35+secrets.randbelow(50),75+secrets.randbelow(50),55+secrets.randbelow(50))
        for y,row in enumerate(GLYPHS[char].split('/')):
            for x,bit in enumerate(row):
                if bit == '1':
                    for dx in range(4):
                        for dy in range(4):
                            dot(x0+x*4+dx+(y//3), y0+y*4+dy, color)
    raw = b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    return code, 'data:image/png;base64,'+base64.b64encode(png).decode()
