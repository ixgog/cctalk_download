import json
import time
import os
import hashlib
import platform
import re
import glob
import requests
import base64
from Crypto.Cipher import AES
from binascii import b2a_hex, a2b_hex

if platform.system() == 'Windows':
    import winreg

def getCurTime():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

if platform.system() == 'Windows':
    # 读取注册表 返回元组
    def QueryRegValue(path, key, rootPath=winreg.HKEY_CURRENT_USER):
        reg = ""
        try:
            reg = winreg.CreateKeyEx(rootPath, path, 0, winreg.KEY_ALL_ACCESS|winreg.KEY_WOW64_32KEY)
        except:
            return False
        if reg != "":
            value = winreg.QueryValueEx(reg, key)
            return value
        else:
            return False
        
    # 写字符串注册表
    def WriteRegStrValue(path, key, value, rootPath=winreg.HKEY_CURRENT_USER):
        reg = ""
        try:
            reg = winreg.CreateKeyEx(rootPath, path, 0, winreg.KEY_ALL_ACCESS|winreg.KEY_WOW64_32KEY)
        except:
            return False
        if reg != "":
            winreg.SetValueEx(reg, key, 0, winreg.REG_SZ, value)
        else:
            return False

def md5Str(str):
    hs = hashlib.md5()
    hs.update(str.encode(encoding='utf-8'))
    return hs.hexdigest()

# 设置环境变量
def setExport(key, value, permanent=False):
    if permanent:
        # 永久修改环境变量
        key = key
        value = value
        cmd = r'setx {} {} /m'.format(key,value)
        os.system(cmd)
    else:
        # 临时修改环境变量
        os.environ[key] = value

# 获取系统类型
def getSystemOS():
    sysstr = platform.system()
    if sysstr == 'Windows':
        return 'Win'
    elif sysstr == 'Darwin':
        return 'Mac'
    elif sysstr == 'Linux':
        return 'Linux'

# 获取环境变量
def getExport(key):
    return os.getenv(key)

def writeFile(data, file_name):
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def readFile(fileFullPath):
    try:
        with open(fileFullPath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except Exception as e:
        return (False, e)

# 获取指定json中指定key
def getJsonKey(filePath, key):
    try:
        with open(filePath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data[key]
    except Exception as e:
        return (False, e)

# 修改json文件中某个值,追加模式,没有则创建
def modifyJsonFile(filePath, key, value):
    try:
        with open(filePath, 'r', encoding='utf-8') as f:
            oldData = json.load(f)
    except:
        oldData = dict()
    try:       
        oldData[key] = value
        with open(filePath, 'w', encoding='utf-8') as f:
            json.dump(oldData, f, ensure_ascii=False, indent=4)
    except:
        return False

# 递归删除文件夹
def deleteFolder(path):
    fileNames = glob.glob(path + r'\*')
    for fileName in fileNames:
        try:
            os.remove( fileName)
        except:
            try:
                os.rmdir( fileName)
            except:
                deleteFolder( fileName)
                os.rmdir( fileName)

# 加密
def encryptStr(key, content):
    model = AES.MODE_OFB #定义模式
    aes = AES.new(key.encode('utf8'),model, b'0000000000000000') #创建一个aes对象
    en_text = aes.encrypt(content.encode('utf-8')) #加密明文
    en_text = base64.encodebytes(en_text) #将返回的字节型数据转进行base64编码
    en_text = en_text.decode('utf8') #将字节型数据转换成python中的字符串类型
    return en_text

# 解密
def decryptStr(key, content):
    model = AES.MODE_OFB #定义模式
    content = base64.decodebytes(content.encode('utf8'))
    aes = AES.new(key.encode('utf8'),model, b'0000000000000000') #创建一个aes对象
    content = aes.decrypt(content)
    return content.decode('utf8').strip('\0')


# 传入data检查token是否合法
def checkTokenLegalFromData(data, key):
    try:
        tokenStr = key + str(data['cur_time'])
        token = md5Str(tokenStr)
    except:
        if data['code'] != 200:
            return False
        return False
    if token == data['token']:
        return True
    else:
        return False

# 检查token是否合法
def checkTokenLegal(token, key, plaintext):
    tokenStr = key + plaintext
    mytoken = md5Str(tokenStr)
    if mytoken == token:
        return True
    else:
        return False


# 处理文件与文件夹不允许的字符串
def cleanUpIllegalCharacter(strPath):
    return strPath.replace('\\', '-').replace('/', '-').replace(':', '-').replace('*', '-').replace('?', '-').replace('"', '-').replace('<', '-').replace('>', '-').replace('|', '-')

# 下载文件
def downdloadFile(url, path):
    # 请求下载地址，以流式的。打开要下载的文件位置。
    with requests.get(url, stream=True) as r, open(path, 'wb') as file:
        # 请求文件的大小单位字节B
        total_size = int(r.headers['content-length'])
        # 以下载的字节大小
        content_size = 0
        # 进度下载完成的百分比
        plan = 0
        # 请求开始的时间
        start_time = time.time()
        # 上秒的下载大小
        temp_size = 0
        # 开始下载每次请求1024字节
        for content in r.iter_content(chunk_size=1024):
            file.write(content)
            # 统计以下载大小
            content_size += len(content)
            # 计算下载进度
            plan = (content_size / total_size) * 100
            # 每一秒统计一次下载量
            if time.time() - start_time > 1:
                # 重置开始时间
                start_time = time.time()
                # 每秒的下载量
                speed = content_size - temp_size
                # KB级下载速度处理
                if 0 <= speed < (1024 ** 2):
                    print(plan, '%', speed / 1024, 'KB/s')
                # MB级下载速度处理
                elif (1024 ** 2) <= speed < (1024 ** 3):
                    print(plan, '%', speed / (1024 ** 2), 'MB/s')
                # GB级下载速度处理
                elif (1024 ** 3) <= speed < (1024 ** 4):
                    print(plan, '%', speed / (1024 ** 3), 'GB/s')
                # TB级下载速度处理
                else:
                    print(plan, '%', speed / (1024 ** 4), 'TB/s')
                # 重置以下载大小
                temp_size = content_size