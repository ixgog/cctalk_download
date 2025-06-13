import os
import re
import sys
import copy
import time
import asyncio
import logging
import logging.handlers
import datetime
import threading
import requests
import utils
from myqss import QSS_MACOS

# 引用之前设置环境变量
# 设置环境变量
utils.setExport('PYPPETEER_DOWNLOAD_HOST', 'http://npm.taobao.org/mirrors')

from pyppeteer import launcher
launcher.DEFAULT_ARGS.remove("--enable-automation")
from pyppeteer import launch

from PyQt5.QtNetwork import QLocalSocket, QLocalServer
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QFile, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QDialog, QListView, QWidget, QFileDialog, QLabel, QMenu, QAction, QToolTip, QPushButton, QCheckBox, QListWidgetItem
from PyQt5.QtGui import QCursor, QFont, QIcon
# ui文件
from ui import ui_main, ui_downInfo

class MyQMainWindow(QMainWindow):
    """对QMainWindow类重写，实现一些功能"""
    def closeEvent(self, event):
        """
        重写closeEvent方法，实现MyQMainWindow窗体关闭时执行一些代码
        :param event: close()触发的事件
        :return: None
        """
        reply = QMessageBox.question(self,
            '提示',
            "是否要退出程序？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            global thread_stop
            thread_stop = True #标记为结束,等待子线程结束进程
            event.accept()
        else:
            event.ignore()

# 异步http请求
class asyncRequest(QThread):
    signal = pyqtSignal(bool, str)
    def __init__(self, url, model="GET", headers='', data=''):
        self.url = url
        self.model = model
        self.headers = headers
        self.data = data
    def run(self):
        try:
            if self.model == "GET":
                response = requests.get(self.url, headers=self.headers)
                if response.status_code == 200:
                    self.signal.emit(True, response.text())
                else:
                    self.signal.emit(False, response.text())
            elif self.model == "POST":
                response = response.post(self.url, headers=self.headers, data=self.data)
                if response.status_code == 200:
                    self.signal.emit(True, response.text())
                else:
                    self.signal.emit(False, response.text())
        except Exception as e:
            self.signal.emit(False, str(e))

# cctalk业务逻辑
class CCtalkBusiness(object):

    # 获取课程数量
    def getCourseCount(self, sid):
        url = 'https://www.cctalk.com/webapi/content/v1.1/series/{}/get_series_info'.format(sid)
        
        response = requests.get(url)
        if response.status_code != 200:
            logger.error('getCourseCount Fail requests Fail:' + str(response.text))
            return False
        try:
            resJson = response.json()
            count = resJson['data']['videoCount']
            return count
        except Exception as ex:
            logger.error('getCourseCount Fail' + str(ex))
            return False
    
    # 获取可以下载的课时，排除预告
    def getCourseEffectiveCount(self, sid):
        url = 'https://www.cctalk.com/webapi/content/v1.2/series/all_video_list?seriesId={}'.format(sid)
        response = requests.get(url)
        if response.status_code != 200:
            return False
        try:
            count = 0
            resJson = response.json()
            for item in resJson['data']['items']:
                if item['liveStatus'] == 11:
                    count += 1
            return count
        except Exception as ex:
            logger.error('getCourseEffectiveCount Fail：' + str(ex))
            return False

    # PC端获取我的课程，相比网页端要全面，包含免费课
    def getMyCourseListPC(self):
        start = 0
        limit = 20
        sidList = list()
        url_model = "https://m.cctalk.com/webapi/content/v1.1/user/my_group_list?start={}&limit={}"
        while True:
            url = url_model.format(start, limit)
            start += limit
            payload = {}
            headers = self.getHeaders()
            headers['Host'] = 'm.cctalk.com'
            logger.info(f"requests {url}")
            response = requests.request("GET", url, headers=headers, data = payload)
            resJson = response.json()
            try:
                status = resJson['status']
                if status != 0:
                    return False
            except Exception as e:
                logger.error('getMyCourseListPC Fail：' + str(e))
                return False
            for item in resJson['data']['items']:
                data = self.getSeriesId(item['groupId'])
                for i in range(0, len(data['idList'])):
                    tempdata = {}
                    tempdata['programmeId'] = data['idList'][i]
                    tempdata['programmeName'] = data['nameList'][i]
                    sidList.append(tempdata)

            if resJson['data']['nextPage'] != True:
                break
        return sidList

    # 获取我的课程列表 json格式 包括课程id,课程名
    def getMyCourseList(self, userId):
        # 循环获取我的课程

        lastTimeline = ""
        headers = self.getHeaders()
        if headers == False:
            return False
        templist = list()
        while(lastTimeline != 0):
            url = 'https://www.cctalk.com/webapi/content/v1.1/user/{}/series_subscribe_list?start=0&limit=20&lastTimeline={}'.format(userId, lastTimeline)
            response = requests.get(url, headers = headers)
            if response.status_code != 200:
                return False
            resJson = response.json()
            lastTimeline = resJson['data']['lastTimeline']
            tempdata = {}
            for item in resJson['data']['programmeList']:
                tempdata['programmeId'] = item['programmeId']
                tempdata['programmeName'] = item['programmeName']
                templist.append(copy.deepcopy(tempdata))
        return templist

    # 获取我的账号id
    def getMyName(self, userId):
        url = 'https://www.cctalk.com/webapi/sns/v1.1/user/{}/info'.format(userId)
        headers = self.getHeaders()
        if headers !=  False:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return False
            else:
                resjson = response.json()
                if resjson['status'] != 0:
                    return False
                return resjson['data']['userName']

    # contentId获取seriesId 列表
    def getSeriesId(self, contentId):
        seriesUrl = 'https://www.cctalk.com/webapi/content/v1.2/series/group/{}/series?limit=50&start=0'
        seriesIdList = list()
        seriesNameList = list()
        url = seriesUrl.format(contentId)
        response = requests.get(url).json()
        for i in response['data']['items']:
            seriesIdList.append(i['seriesId'])
            seriesNameList.append(i['seriesName'])
        data = {}
        data['idList'] = seriesIdList
        data['nameList'] = seriesNameList
        return data

    # 通过sid返回videoidlist
    def getVideoInfo(self, sid):
        allVideoListUrl = 'https://www.cctalk.com/webapi/content/v1.2/series/all_video_list?seriesId={}&showStudyTime=true'
        videoData = {}
        videoList = list()
        response = requests.get(allVideoListUrl.format(sid)).json()
        try:
            count = len(response['data']['items'])
            for (i, item) in zip(range(0, count), response['data']['items']):
                videoData.clear()
                videoData['videoId'] = item['videoId']
                videoData['videoName'] = str(i + 1) + '、' + (item['videoName'])
                videoData['liveStatus'] = item['liveStatus']
                videoData['mediaTotalTime'] = item['mediaTotalTime']
                videoData['isTrail'] = item['isTrail']
                try:
                    videoData['forecastEndDate'] = item['forecastEndDate']
                except:
                    videoData['forecastEndDate'] = None
                videoList.append(copy.deepcopy(videoData))
            return videoList
        except Exception as ex:
            logger.info(allVideoListUrl.format(sid) + response + ex)
            return False

    # 通过videoId 获取版权保护状态
    def getVideoisOpenProtection(self, videoId):
        detailUrl = 'https://www.cctalk.com/webapi/content/v1.1/video/detail?videoId={}'.format(videoId)
        response = requests.get(detailUrl)
        if response.status_code == 200:
            return response.json()['data']['isOpenProtection']
        return False

    # 通过videoId 获取下载链接
    def getSourceUrl(self, videoId, isTrail=True):
        # 当前为登录状态，只读取detailurl
        detailUrl = 'https://www.cctalk.com/webapi/content/v1.1/video/detail?videoId={}'.format(videoId)
        videoUrl = requests.get(detailUrl, headers=self.getHeaders()).json()['data']['videoUrl']
        return videoUrl

    def getSourceName(self, sourceUrl):
        if len(sourceUrl) > 0:
            try:
                com = re.compile(r'record\/(.*?).mp4')
                result = com.findall(sourceUrl)[0]
            except:
                com = re.compile(r'com\/(.*?).mp4')
                result = com.findall(sourceUrl)[0]
            return result

    # 根据sid获取下载地址
    def getDownUrl(self, id):
        sid = id
        # 课程总容器
        courseInfo = list()
        # 初始化series课程容器
        seriesInfo = list()
        seriesData = {}
        try:
            videoInfoList = self.getVideoInfo(sid)
            for vinfo in videoInfoList:
                if vinfo['mediaTotalTime'] > 0 and vinfo['liveStatus'] == 11:
                    seriesData.clear()
                    seriesData['sourceUrl'] = self.getSourceUrl(vinfo['videoId'], True)
                    seriesData['seriesId'] = sid
                    seriesData['videoId'] = vinfo['videoId']
                    seriesData['isTrail'] = vinfo['isTrail']
                    seriesData['sourceFileName'] = self.getSourceName(seriesData['sourceUrl'])
                    seriesData['realName'] = vinfo['videoName']
                    seriesData['renameStr'] = 'rename {}.mp4 {}.mp4'.format(seriesData['sourceFileName'], vinfo['videoName'])
                    seriesInfo.append(copy.deepcopy(seriesData))
            seriesData.clear()
            seriesData['videoList'] = seriesInfo
            seriesData['seriesId'] = sid
            courseInfo.append(copy.deepcopy(seriesData))
            seriesData.clear()
            seriesData['seriesList'] = courseInfo
            return seriesData
        except Exception as e:
            logger.info("get download url fail:" + e)
            return False

    # 根据sid获取版权保护开启情况
    def getCourseIsOpenProtection(self, sid):
        videoInfoList = self.getVideoInfo(sid)
        for vinfo in videoInfoList:
            if vinfo['mediaTotalTime'] > 0 and vinfo['liveStatus'] == 11:
                if vinfo['isTrail'] == True:
                    continue
                else:
                    return self.getVideoisOpenProtection(vinfo['videoId'])
        return False

    
    # 根据cookie文件获取headers
    def getHeaders(self):
        global CLUB_AUTH
        if CLUB_AUTH == '':
            data = utils.readFile(cookieFilePath)
            if type(data) == tuple:
                return False
            for item in data:
                if item['name'] == 'ClubAuth':
                    CLUB_AUTH = item['value']
                    break        
        headers = {
            'Connection': 'keep-alive',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36',
            'Cookie': 'ClubAuth={}'.format(CLUB_AUTH)
            }
        return headers

# 异步获取课程信息
class asyncGetCourseInfo(QThread):
    signal = pyqtSignal(bool, int, int, list)
    def __init__(self, sid):
        super(asyncGetCourseInfo,self).__init__()
        self.sid = sid
    def run(self):
        # 判断是否开启了版权保护
        try:
            ccb = CCtalkBusiness()
            isOpen = ccb.getCourseIsOpenProtection(self.sid)
            if isOpen == True:
                self.signal.emit(False, 0, 0, [])
                return None    
            count = ccb.getCourseCount(self.sid)
            if count == False:
                self.signal.emit(False, 1, 0, [])    
                return None
            effectiveCount = ccb.getCourseEffectiveCount(self.sid)
            if effectiveCount == False:
                self.signal.emit(False, 1, 0, [])    
                return None
            # 获取下载地址
            CCBusiness = CCtalkBusiness()
            vList = CCBusiness.getVideoInfo(self.sid)
            if vList == False:
                self.signal.emit(False, 1, 0, [])    
                return None
            self.signal.emit(True, count, effectiveCount, vList)

        except Exception as e:
            logger.warning("获取课程信息失败：" + str(e))
            self.signal.emit(False, 1)


        

# ui_main
class CCtalkUi(object):
    def __init__(self):
        self.CCBusiness = CCtalkBusiness()

    def myInit(self):
        self.app = QApplication(sys.argv)

        # --------单例
        serverName = 'ccdownload'
        socket = QLocalSocket()
        socket.connectToServer(serverName)
        
        # 如果连接成功，表明server已经存在，当前已有实例在运行
        if socket.waitForConnected(500):
            # QMessageBox.warning(self, '提示', '已经有一个程序在运行，请勿重复启动，如没有进程界面，请到任务管理器中找到ccdownload.exe进程并关闭')
            logger.warning('已经有一个程序在运行')
            return(self.app.quit())
        
        # 没有实例运行，创建服务器   
        self.localServer = QLocalServer()     
        self.localServer.listen(serverName) 
        # --------单例end

        self.MainWindow = MyQMainWindow() #使用重写的类
        self.ui = ui_main.Ui_MainWindow()
        self.ui.setupUi(self.MainWindow)

        # 加载qss文件 和 ico
        self.MainWindow.setStyleSheet(QSS_MACOS)
        self.MainWindow.setWindowIcon(QIcon(':icon/ccdownload.ico'))

        self.MainWindow.setFixedSize(self.MainWindow.width(), self.MainWindow.height()); # 固定大小
        self.MainWindow.setWindowTitle('CCtalk下载工具')

        self.ui.comb_course.setStyleSheet(
            "QComboBox {combobox-popup: 0;}"# 滚动条
            "QAbstractItemView::item {height: 30px;}")
        self.ui.comb_course.setView(QListView())
        self.ui.edit_savePath.setFocusPolicy(Qt.NoFocus) # 设置编辑框可选中不可编辑

        # 隐藏下载信息与进度条
        self.setDownLoadInfoShow(False)
        # 隐藏退出按钮
        self.ui.btn_quit.setVisible(False)

        # 信号槽
        self.ui.btn_login.clicked.connect(self.loginCCtalk)
        self.ui.btn_selectPath.clicked.connect(self.selectFolder)
        self.ui.btn_download.clicked.connect(self.checkiIsshowDownDlg)
        self.ui.btn_quit.clicked.connect(self.quitLogin)
        
        self.showMainWindow()

    def showMainWindow(self):
        # 更新用户信息
        self.checkUserInfo()
        try:
            self.MainWindow.show()
            sys.exit(self.app.exec_())
        except:
            self.localServer.close()

    # 设置下载信息是否显示
    def setDownLoadInfoShow(self, isShow):
        if isShow == False:
            self.MainWindow.setFixedHeight(self.ui.btn_selectPath.y() + self.ui.btn_selectPath.height() + 30)
        else:
            self.MainWindow.setFixedHeight(self.ui.progressBar_down.y() + self.ui.progressBar_down.height() + 30)
        self.ui.label_currentDown.setVisible(isShow)
        self.ui.label_currentTitle.setVisible(isShow)
        self.ui.label_progressTitle.setVisible(isShow)
        self.ui.progressBar_down.setVisible(isShow)
        if utils.getSystemOS() == 'Win':
            self.ui.label_downPercentage.setVisible(False)
        else:
            self.ui.label_downPercentage.setVisible(isShow)

    def loginCCtalk(self):
        # 判断浏览器是否存在
        pyppeteerPath = os.getenv("LOCALAPPDATA") + '/pyppeteer'
        if os.path.exists(pyppeteerPath) == False:
            QMessageBox.information(self.MainWindow,
                '提示',
                "首次启动需要下载依赖项,请耐心等待\n下载完成会启动一个全新的浏览器进入CCtalk登录页面,登录完成后窗口自动关闭")
            self.ui.label_currentDown.setText('浏览器依赖')
            self.setProgress(0)
            self.setDownLoadInfoShow(True)
            self.timer = QTimer()  # 初始化定时器
            self.timer.timeout.connect(self.DownPyppeteer)
            self.timer.start(1 * 1000)
        t = threading.Thread(target=login, name='funciton')
        t.start()
        self.ui.btn_login.setText('启动中')
        self.ui.btn_login.setDisabled(True)
    
    def DownPyppeteer(self):
        
        global pyppeteer_isdown
        if pyppeteer_isdown == True:
            self.setDownLoadInfoShow(False)
            self.ui.btn_login.setText('请登录..')
            self.timer.stop()
        if self.ui.progressBar_down.value() == 95:
            return False
        self.setProgress(self.ui.progressBar_down.value() + 1)

    def checkUserInfo(self):
        #更新配置
        global USER_ID
        global SAVA_PATH
        data = utils.readFile(configFilePath)
        if type(data) != tuple:
            try:
                USER_ID = data['userId']
            except:
                pass
            try:
                self.ui.edit_savePath.setText(data['savePath'])
                SAVA_PATH = data['savePath']
            except:
                pass

        # 判断cookie文件是否登录
        if os.path.exists(cookieFilePath) == False:
            return False
        # 请求个人信息:
        if USER_ID == "":
            # QMessageBox.critical(self.MainWindow, '提示', "用户信息获取失败")
            return False
        name = self.CCBusiness.getMyName(USER_ID)
        if name != False:
            global USER_NAME
            USER_NAME = name            
        self.courseList = self.CCBusiness.getMyCourseListPC()
        if self.courseList != False:
            self.ui.label_user.setText(name)
            self.ui.btn_login.setText('已登录')
            self.ui.btn_login.setDisabled(True)
            self.ui.statusbar.showMessage("当前用户id：" + USER_ID)
            self.ui.btn_quit.setVisible(True)
        else:
            QMessageBox.warning(self.MainWindow, '警告', '登录已过期,请重新登录')
            self.ui.btn_login.setText('登录')
            self.ui.btn_login.setDisabled(False)
            return False
        for item in self.courseList:
            self.ui.comb_course.addItem(item['programmeName'])
        if len(self.courseList) > 0:
            self.ui.comb_course.setCurrentIndex(0)
        self.ui.btn_download.setFocus()
    
    def quitLogin(self):
        ret = QMessageBox.question(self.MainWindow, "提示", "退出登录后需要重新启动程序，是否继续？")
        if ret == QMessageBox.Yes:
            os.remove(cookieFilePath)
            utils.deleteFolder(curPath + "/userdata")
            sys.exit()
    
    # 选择保存路径
    def selectFolder(self):
        directory = QFileDialog.getExistingDirectory(self.MainWindow, "getExistingDirectory", "./")
        if directory:
            self.ui.edit_savePath.setText(directory)
            self.savePath = directory
            utils.modifyJsonFile(configFilePath, 'savePath', directory)
            global SAVA_PATH
            SAVA_PATH = directory

    # 判断是否显示下载信息
    def checkiIsshowDownDlg(self):
        # 判断是否选择保存路径
        global SAVA_PATH
        if USER_NAME == '':
            QMessageBox.critical(self.MainWindow, '提示', '登录后选择课程才能下载')
            return False
        if SAVA_PATH == '':
            QMessageBox.critical(self.MainWindow, '提示', '请先选择保存路径')
            return False
        self.ui.btn_download.setText("解析中...")
        self.ui.btn_download.setDisabled(True)
        self.downDlg = DownloadDlg()
        self.downSid = self.courseList[self.ui.comb_course.currentIndex()]['programmeId']
        self.downName = self.ui.comb_course.currentText()
        self.gt = asyncGetCourseInfo(self.downSid)
        self.gt.start()
        self.gt.signal.connect(self.showDownInfoDlg)
        

    # 显示下载详情窗口
    def showDownInfoDlg(self, ret, count, effectiveCount, vList):
        self.ui.btn_download.setText("下载")
        self.ui.btn_download.setDisabled(False)
        if ret == False:
            if count == 0:
                QMessageBox.warning(self.MainWindow, '提示', '此课程已开启版权保护，工具暂时无法下载')
            elif count == 1:
                 QMessageBox.critical(self.MainWindow, '提示', '请求课程数据失败')
            return False
        self.downDlg.setCourseInfo(count, effectiveCount, self.downName, vList)
        ret = self.downDlg.showDlg()
        if ret == 0:
            self.MainWindow.raise_()
            return False
        
        # 开始下载
        self.dt = DownLoadThread(self.downSid, self.ui.comb_course.currentText()) #一定要加self,否则局部变量被销毁线程就结束了
        self.dt.start()
        self.dt.signal.connect(self.downloadSignalToProcess)
 
        # 显示进度条
        self.ui.label_currentDown.setText('解析中...')
        self.setDownLoadInfoShow(True)
        self.setProgress(0)

    # 下载线程的信号处理
    def downloadSignalToProcess(self, signType, conent):
        if signType == 1:
            self.setProgress(int(conent))
        elif signType == 2:
            self.ui.label_currentDown.setText("正在下载{}".format(conent))
            self.ui.btn_download.setDisabled(True)
        elif signType == 3:
            QMessageBox.information(self.MainWindow, '提示', conent) 
        elif signType == 4:
            QMessageBox.information(self.MainWindow, '提示', conent)
            self.setDownLoadInfoShow(False)
            self.ui.btn_download.setDisabled(False)

    def setProgress(self, value):
        self.ui.progressBar_down.setProperty("value", int(value))
        self.ui.label_downPercentage.setText(str(int(value)) + '%')

# ui_downInfo
class DownloadDlg(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = ui_downInfo.Ui_Dialog()
        self.ui.setupUi(self)

        # 加载qss文件
        self.setStyleSheet(QSS_MACOS)
        self.setWindowIcon(QIcon(':icon/ccdownload.ico'))

        self.setFixedSize(self.width(), self.height()); # 固定大小

        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowTitle("下载")
        self.ui.label_downInfo.setWordWrap(True)
        self.ui.label_downInfo.setAlignment(Qt.AlignCenter)
        self.ui.label_downInfo.setStyleSheet("QLabel {font-size:14px;color:rgb(65,134,228);font-weight:bold;}")
        self.ui.label_downInfo.setFont(QFont("Microsoft YaHei"))

        self.needIntegral = 0

        # 信号槽
        self.ui.btn_dwonSelect.clicked.connect(self.downSelect)
        self.ui.btn_selectAll.clicked.connect(self.selectAllOrCancelSelection)
        self.ui.btn_no.clicked.connect(self.btnNo)
        
        
    def showDlg(self):
        self.show()
        return self.exec_()
    
    # 获取checkout list
    def getCheckList(self):
        count = self.ui.list_video.count()  # 得到QListWidget的总个数
        cb_list = [self.ui.list_video.itemWidget(self.ui.list_video.item(i))
                  for i in range(count)]  # 得到QListWidget里面所有QListWidgetItem中的QCheckBox
        return cb_list

    # 全选/取消全选
    def selectAllOrCancelSelection(self):
        cb_list = self.getCheckList()
        if self.ui.btn_selectAll.text() == "全选":
            self.ui.btn_selectAll.setText("取消全选")
            for cb in cb_list:
                cb.setChecked(True)
        else:
            self.ui.btn_selectAll.setText("全选")
            for cb in cb_list:
                cb.setChecked(False)

    # 下载已选中的课程
    def downSelect(self):

        cb_list = self.getCheckList()
        chooses = []  # 存放被选择的数据
        for cb in cb_list:  # type:QCheckBox
            if cb.isChecked():
                chooses.append(cb.text())
        if len(chooses) <= 0:
            QMessageBox.warning(self, '提示', "至少选择一节课程下载")
            return False
        global DOWN_LIST
        DOWN_LIST.clear()
        DOWN_LIST = copy.deepcopy(chooses)
        self.accept() # 返回1
    
    def btnNo(self):
        self.reject() # 返回0

    def setCourseInfo(self, count, effectiveCount, name, vList):
        self.vList = vList
        nameList = list()
        for item in self.vList:
            if item['liveStatus'] == 11:
                nameList.append(item['videoName'])
        for vName in nameList:
            box = QCheckBox(vName)	# 实例化一个QCheckBox，把文字传进去
            box.setChecked(True)
            item = QListWidgetItem()  # 实例化一个Item，QListWidget，不能直接加入QCheckBox
            self.ui.list_video.addItem(item)	# 把QListWidgetItem加入QListWidget
            self.ui.list_video.setItemWidget(item, box)  # 再把QCheckBox加入QListWidgetItem
        self.needIntegral = effectiveCount
        self.ui.label_downInfo.setText("当前选择课程为:\n[{}]\n共计 {} 课时,已上传录播且可下载的有{}课时".format(name, count, effectiveCount, effectiveCount))

# 下载线程
class DownLoadThread(QThread):
    signal = pyqtSignal(int, str) # 定义信号 1：进度条 2：当前下载的课时 3：消息 4：完成
    def __init__(self, sid, courseName):
        super(DownLoadThread,self).__init__()
        self.sid = sid
        self.courseName = courseName
    def run(self):
        # 获取下载地址
        CCBusiness = CCtalkBusiness()
        data = CCBusiness.getDownUrl(self.sid)
        if data == False:
            self.signal.emit(3, "解析数据失败")
            return None
        global SAVA_PATH
        # 创建文件夹
        self.courseName = utils.cleanUpIllegalCharacter(self.courseName)
        if os.path.exists(SAVA_PATH+ '/' + self.courseName) is False:
            os.mkdir(SAVA_PATH+ '/' + self.courseName)
        
        try:
            global DOWN_LIST
            for item in data['seriesList']:
                for (vInfo, counter) in zip(item['videoList'], range(0, len(item['videoList']))):
                    # 如果课程不在选中下列列表中则跳过
                    if vInfo['realName'] not in DOWN_LIST:
                        logger.info(vInfo['realName'] + "不在选择列表中")
                        continue
                    videoName = utils.cleanUpIllegalCharacter(vInfo['realName'])
                    self.signal.emit(2, "[" + str(counter + 1) + "/" +  str(len(item['videoList'])) + "]" + vInfo['realName'])
                    filePath = SAVA_PATH + '/{}/{}.mp4'.format(self.courseName, videoName)
                    if os.path.exists(filePath) == True:
                        # 课程已存在，并且大小与线上一致，跳过此下载
                        response = requests.head(vInfo['sourceUrl'])
                        if response.status_code == 200:
                            if int(response.headers['Content-Length']) == int(os.path.getsize(filePath)):
                                logger.info(filePath + '已存在，跳过下载')
                                continue
                    response = requests.head(vInfo['sourceUrl'])
                    if response.status_code != 200:
                        self.signal.emit(4, "下载失败")
                        raise Exception("链接已失效")
                    else:
                        ret = self.downdloadFile(vInfo['sourceUrl'], filePath)
                        logger.info("down suc " + filePath)
        except Exception as e:
            logger.error(e)
        else:
            self.signal.emit(4, "下载完成")
        
    
    # 下载文件
    def urlDownload(self, url, path):
        try:
            ret = requests.get(url, stream=True)
            with open(path, 'wb') as f:
                for ch in ret:
                    f.write(ch)
            return True
        except:
            return False

    # 下载文件
    def downdloadFile(self, url, path):
        try:
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
                    plan = int((content_size / total_size) * 100)
                    # 每一秒统计一次下载量
                    if time.time() - start_time > 1:
                        # # 重置开始时间
                        # start_time = time.time()
                        # # 每秒的下载量
                        # speed = content_size - temp_size
                        # # KB级下载速度处理
                        # if 0 <= speed < (1024 ** 2):
                        #     logger.info(str(plan) + '%---' + str(int(speed / 1024)) + 'KB/s')
                        # # MB级下载速度处理
                        # elif (1024 ** 2) <= speed < (1024 ** 3):
                        #     logger.info(str(plan) + '%---' + str(int(speed / (1024 ** 2))) + 'MB/s')
                        # # GB级下载速度处理
                        # elif (1024 ** 3) <= speed < (1024 ** 4):
                        #     logger.info(str(plan) + '%---' + str(int(speed / (1024 ** 3))) + 'GB/s')
                        # # TB级下载速度处理
                        # else:
                        #     logger.info(str(plan) + '%---' + str(int(speed / (1024 ** 4))) + 'TB/s')
                        # 重置以下载大小
                        temp_size = content_size
                    self.signal.emit(1, str(int(plan)))
            return True
        except:
            logger.error("download " + path + " error")
            return False

# 浏览器控制类
class CCtalkLogin(object):
    async def init(self):
        self.browser=await launch(
            {
                'headless': False,
                'dumpio': True,
                'autoClose': True,                
                'handleSIGINT':False,
                'handleSIGTERM': False,
                'handleSIGHUP': False,
                'userDataDir': curPath + '/userdata',
                'args': [
                    '--no-sandbox',
                    '--disable-infobars',  # 关闭自动化提示框
                    '--window-size=1366,850',
                ]
            }
        )
        self.page=await self.browser.newPage()
        await self.page.setViewport({'width': 1366, 'height': 768})
        await self.page.setUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36"
        )

        global pyppeteer_isdown
        pyppeteer_isdown = True

        await self.page.goto("https://my.cctalk.com/account")
        while 'login' in self.page.url:
                await asyncio.sleep(1)
                continue

        await self.page.goto('https://www.cctalk.com/u/subscription/')
        ret=await self.page.content()  # 获取html标签
        # 获取用户id
        # logger.info('html:' + ret)
        com = re.compile(r'userId:(.*),')
        result = com.findall(ret)
        if len(result) > 0:
            global USER_ID
            USER_ID = result[0].replace(' ', '')
            utils.modifyJsonFile(configFilePath, 'userId', USER_ID)
        cookie=await self.page.cookies()
        # 保存cookie
        utils.writeFile(cookie, cookieFilePath)
        await self.browser.close()
        mainWindow.checkUserInfo()


def login():
    cctalk=CCtalkLogin()
    loop=asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(cctalk.init())

if __name__ == "__main__":
    curPath = os.path.dirname(os.path.realpath(sys.argv[0]))

    # ---------------初始化日志------------------------
    logFilePath = './log/CCdownload.log'
    logger = logging.getLogger('mylogger')
    logger.setLevel(logging.DEBUG)

    if os.path.exists(logFilePath) is False:
        os.mkdir(os.path.dirname(logFilePath))
    # 文件
    rf_handler = logging.handlers.TimedRotatingFileHandler(
        logFilePath, when='midnight', interval=1, backupCount=3, encoding='utf-8', atTime=datetime.time(0, 0, 0, 0))
    rf_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    # 屏幕
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(sh)
    logger.addHandler(rf_handler)
    logger.info('log init suc')
    # -------------日志初始化结束-----------------------
    
    logger.info('当前程序运行路径:' + curPath)

    thread_stop = True
    login_status = False
    pyppeteer_isdown = False

    SAVA_PATH = ''
    USER_NAME = ''
    USER_ID = ''
    CLUB_AUTH = ''

    DOWN_LIST = list()
    
    QSS_PATH = './qss/macos.qss'
    
    cookieFilePath = curPath+'/config/c.json'
    if os.path.exists(os.path.dirname(cookieFilePath)) == False:
        os.mkdir(os.path.dirname(cookieFilePath))
    
    configFilePath = curPath+'/config/config.json'

    # 启动界面
    mainWindow = CCtalkUi()
    mainWindow.myInit()

    
