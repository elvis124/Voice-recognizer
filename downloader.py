from __future__ import unicode_literals

import os, sys
import re
import shutil
import traceback
import threading
from youtube_dl.downloader.http import HttpFD
from youtube_dl.downloader.hls import HlsFD
from youtube_dl.downloader.M3u8Downloader import FFmpegFD as FFmpegFDEx
from youtube_dl.downloader.OldM3u8Downloader import WSM3u8FD as WSM3u8FD
from youtube_dl.downloader.external import FFmpegFD
from youtube_dl.downloader.httpCrul import HttpCurl
from youtube_dl.utilsEX import (
    get_top_host,
    GoogleAnalytics
)

import youtube_dl
from youtube_dl.compat import (
    compat_str,
)
from youtube_dl.WS_Extractor import (
    YoutubeDLPatch4Single
)
from urlparse import urlparse


class downloader:
    def buildOptions(self, verbose=False):
        ydl_opts = {}
        ydl_opts['debug_printtraffic'] = 1
        ydl_opts['playlistend'] =  1
        #ydl_opts['socket_timeout'] = 600
        #2017.08.10
        ydl_opts['source_address'] = '0.0.0.0'
        ydl_opts['verbose'] = 1
        ydl_opts['continuedl'] = 1
        ydl_opts['nopart'] = True
        ydl_opts['skip_unavailable_fragments'] = False
        ydl_opts['fragment_retries']  = 10
        ffmpeg_name = os.getenv('KVFfmpegPath')
        if ffmpeg_name is None:
            debug('get KVFfmpegPath failed')
            debug('Try Get KVFfmpegPath Begin----------------------------------------------------')
            if sys.platform == 'win32':
                ffmpeg_name = r'DownloadRes\ffmpeg.exe' if os.path.exists(r'DownloadRes\ffmpeg.exe') else 'ffmpeg.exe'
            else:
                ffmpeg_name = 'ffmpeg'
            try:
                # 日文路径，os.path.join(os.path.abspath(os.curdir), ffmpeg_name)会出异常，所以用相对路径置之
                try:
                    ydl_opts['ffmpeg_location'] = os.path.join(os.path.abspath(os.curdir), ffmpeg_name)
                except:
                    ydl_opts['ffmpeg_location'] = ffmpeg_name

                if not os.path.exists(ydl_opts['ffmpeg_location']):
                    debug('_file__Begin')
                    debug(__file__)
                    ydl_opts['ffmpeg_location'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), ffmpeg_name)
                    debug('_file__End')
                debug(ydl_opts['ffmpeg_location'])
            except:
                pass
            debug('Try Get KVFfmpegPath End----------------------------------------------------')
        else:
            debug('get KVFfmpegPath:' + ffmpeg_name)
            ydl_opts['ffmpeg_location'] = ffmpeg_name
        return ydl_opts

    def __init__(self, callback, infos):
        self._callback = callback
        self._imageSavePath = infos['imageSavePath']
        self._infos = infos
        self._cancel = False
        self._subtitleFile = ''
        self._downloadingFile = ''
        self._ydl = YoutubeDLPatch4Single(self.buildOptions(False))

        if sys.platform == 'win32':
            self._GA = GoogleAnalytics( 'UA-100395100-3')
        else:
            self._GA = GoogleAnalytics( 'UA-100395100-4')

    #下载进度回调钩子
    def progress_hook(self, s):
        if self._cancel:
            raise Exception('cancel')

        if self.downloadThumbailAndIcon:
            return

        def safeGetValue(dict, key, default):
            value = dict.get(key, default)
            return  value if value else default

        if s['status'] == 'downloading':
            downloaded_bytes = safeGetValue(s, 'downloaded_bytes', 0)
            total_bytes = safeGetValue(s, 'total_bytes', 0) if ('total_bytes' in s) else  safeGetValue(s, 'total_bytes_estimate', 0)
            self._infos['downloadingFiles'][self._downloadingFile]['downloadedSize'] = downloaded_bytes
            total_bytes = total_bytes if total_bytes else 1024 * 1024 * 1024 * 2
            if total_bytes < (downloaded_bytes-1024):
                print( 'total_bytes < downloaded_bytes total_bytes：%d downloaded_bytes：%d' % (total_bytes, downloaded_bytes))
                total_bytes = downloaded_bytes + 50 * 1024 * 1024
            self._infos['downloadingFiles'][self._downloadingFile]['fileSize'] = total_bytes
            downloaded_bytes = total_bytes = 0
            for item in self._infos['downloadingFiles'].values():
                downloaded_bytes += safeGetValue(item, 'downloadedSize', 0)
                total_bytes += safeGetValue(item, 'fileSize', 0)

            msg = {
                'event': 'downloading',
                'fileSize': total_bytes,
                'downloadedSize': downloaded_bytes,
            }

            if s.get('speed', None):
                msg['speed'] = s['speed']

            if self._callback:
                self._callback(msg)

    def testDownloader(self, func, info, fileName = None):
        if fileName:
            self.downloaderTestResult = func(info, fileName)
        else:
            self.downloaderTestResult = func(info)


    #真实下载
    def get_suitable_downloader(self, filename, info):
        params = self._ydl.params
        fd = youtube_dl.downloader.get_suitable_downloader(info, {})(self._ydl, params)
        if type(fd) == HttpFD:
            #如果目标路径下存在该文件那么说明使用的是httpFD
            if not os.path.exists(filename):
                debug('-----------------------Test HttpCurl------------------')
                hc = HttpCurl(self._ydl, params)
                self.downloaderTestResult = False
                t = threading.Thread(target=self.testDownloader, args=(hc.testUrl, info))
                t.start()
                t.join(10)
                if self.downloaderTestResult:
                    fd = hc
                    if self._infos.get('speedUp', 'False') == 'True':
                        fd.openSpeedup()
                debug('-----------------------Test HttpCurl %s------------------' % ('success' if type(fd) ==HttpCurl else 'fail'))
        elif type(fd) in [FFmpegFD, HlsFD]:
            if self._infos.get('url', '').find('youku') > -1 or self._infos.get('url', '').find('tudou') > -1 or \
                            self._infos.get('url', '').find('iview.abc.net.au')>-1:
                return HlsFD(self._ydl, params)

            try:
                if 'http_headers' in info and info['http_headers'] and 'Accept-Encoding' in info['http_headers']:
                    info['http_headers'].pop('Accept-Encoding')
            except:
                pass
            debug('-----------------------Select M3u8 Download Begin------------------')
            #目标下存在DS后缀的同名文件，且文件大小大于20K，那么就直接使用WSM3u8FD
            tempFileName = '%s.ds' % filename
            if os.path.exists(tempFileName) and os.path.getsize(tempFileName) > 1024 * 20:
                debug('-----------------------Select M3u8 Download Use WSM3u8FD------------------')
                dl = WSM3u8FD(self._ydl, params)

            elif os.path.exists(filename):
                debug('-----------------------Select M3u8 Download Use FFmpegFDEx------------------')
                #或者如果存在不包含DS的目标文件，那么说明使用了FFMEPG
                dl = FFmpegFDEx(self._ydl, params)
            else:
                debug('-----------------------Test WSM3u8FD------------------')
                dl = WSM3u8FD(self._ydl, params)
                if not dl.testUrl(filename, info):
                    dl = None
                debug('-----------------------Test WSM3u8FD %s------------------' % ('success' if dl else 'fail'))
                if not dl:
                    dl = FFmpegFDEx(self._ydl, params)

            debug('-----------------------Select M3u8 Download End------------------')
            fd = dl
        debug(fd)
        return fd

    def _beforeDownload(self, filename, info):
        debug('_download begin %s' % filename)
        debug('......info......')
        debug(info)
        debug('......info......')
        if type(filename) != compat_str:
            try:
                filename = unicode(filename)
            except:
                filename = filename.decode('utf-8')
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename))
        return filename

    def _download(self, filename, info):
        filename = self._beforeDownload(filename, info)
        if type(info) is not dict:
            info = eval(info)
            #'protocol': 'http_dash_segments',
        url = self._infos.get('url', None)
        host = get_top_host(url) if url else ''
        for i in range(3):
            try:
                debug('downloader.py _download try %d' % i)
                if info.has_key('fragments'):
                    info['protocol'] = 'http_dash_segments'
                fd = self.get_suitable_downloader(filename, info)
                fd.add_progress_hook(self.progress_hook)
                if fd.download(filename, info):
                    try:
                        url = self._infos.get('url', None)
                        url = get_top_host(url) if url else ''
                        self._GA.send('event', 'download_success', type(fd).__name__, host)
                    except:
                        pass
                    break
                else:
                    raise Exception('downloadFail')
            except:
                if self._cancel:
                    break
                debug(traceback.format_exc())
                if i == 2:
                    try:
                        self._GA.send('event', 'download_fail', type(fd).__name__, host)
                        self._GA.send('event', 'fail_detail', host, traceback.format_exc())
                    except:
                        pass
                    raise Exception(traceback.format_exc())
                else:
                    threading._sleep(1)
        debug('_download end')

    def downloadSubtitle(self):
        try:
            if ('subtitleUrl' not in self._infos  or self._infos.get('subtitleUrl', None) == None):
                if ('subtitle_data' not in self._infos or self._infos.get('subtitle_data', None) == None):
                    return

            self._subtitleFile = os.path.join(self._downloadtempPath, '%s.srt' % self._infos['fileNameWithoutExt'])
            if os.path.exists(self._subtitleFile):
                return

            if 'subtitleUrl' in self._infos:
                subtitleUrl = self._infos.get('subtitleUrl')
                from sniffer import (
                    YoutubeSubtitle
                )
                str = YoutubeSubtitle(self._ydl).getSubtitleContent(subtitleUrl)
            else:
                str = self._infos['subtitle_data']

            if str != '':
                f = open(self._subtitleFile, 'wb')
                f.write(str)
                f.close()

            if os.path.exists(self._subtitleFile):
                msg = {
                    'event':'download_Subtitle',
                    'filePath': self._subtitleFile
                }
                if self._callback:
                    self._callback(msg)
        except Exception as e:
            print (e)
            pass

    def downloadWebSiteIcon(self, url, savePath):
        if url == '':
            return

        debug('downloadWebSiteIcon begin')
        try:
            if (not re.search(r'//', url)):
                url = 'http://' + url
            o = urlparse(url)
            fileName = os.path.join(savePath, '%s.ico' % o.netloc)
            if not os.path.exists(fileName):
                webpage = self._ydl.urlopen(url).read()
                mobj = re.search(r'<link rel="shortcut icon"\s*href="([^\"]+)"', webpage)
                faviconURL = ''
                if mobj:
                    faviconURL = mobj.group(1)

                    if (not re.search(r'//', faviconURL)):
                        if faviconURL.find(r'/') == 0:
                            faviconURL = 'http://'+ o.netloc + faviconURL
                        else:
                            faviconURL = 'http://' + faviconURL

                if not os.path.exists(fileName) and faviconURL != '':
                    info = {'url':faviconURL}
                    self._downloadSmallFile(fileName, info)

                if not os.path.exists(fileName):
                    faviconURL = '%s://%s/favicon.ico' % (o.scheme, o.netloc)
                    self._downloadSmallFile(faviconURL, fileName)

            if os.path.exists(fileName):
                msg = {
                    'event':'download_icon',
                    'filePath': fileName
                }
                if self._callback:
                    self._callback(msg)
        except:
            debug(traceback.format_exc())
            pass
        debug('downloadWebSiteIcon end')

    def downloadThumbnail(self, url, fileName):
        debug('downloadThumbnail begin')
        try:
            # 置位，以便于ffmpeg获取
            self._infos['thumbnail_filename'] = fileName
            if not url or url == '':
                return
            if not os.path.exists(fileName):
                self._downloadSmallFile(url, fileName)

            if os.path.exists(fileName):
                msg = {
                    'event':'download_thumbnail',
                    'filePath': fileName
                }
                if self._callback:
                    self._callback(msg)
        except:
            debug(traceback.format_exc())
            pass
        debug('downloadThumbnail end')


    def downloadThumbnailAndIcon(self, title):
        self.downloadThumbailAndIcon = True
        try:
            self.downloadWebSiteIcon(self._infos.get('url'), self._infos['imageSavePath'])
            thumbnailFilename = os.path.join(self._infos['imageSavePath'], '%s.jpg' % title)
            self.downloadThumbnail(self._infos.get('thumbnail', ''), thumbnailFilename)
        except:
            pass
        finally:
            self.downloadThumbailAndIcon = False

    def _downloadSmallFile(self, url, filename):
        debug('begin _downloadSmallFile')
        try:
            if not os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename))
            for proto in ['http', 'https']:
                if re.match(r'http', url):
                    tempUrl = url
                else:
                    if re.match(r'://', url):
                        tempUrl = '%s%s' % (proto , url)
                    elif re.match(r'//', url):
                        tempUrl = '%s:%s' % (proto , url)
                    else:
                        tempUrl = '%s://%s' % (proto , url)
                try:
                    webpage = self._ydl.urlopen(tempUrl).read()
                    f = open(filename, 'wb')
                    f.write(webpage)
                    f.close()
                    debug('end _downloadSmallFile Sucess')
                    break
                except Exception as e:
                    if re.match(r'http', url):#原来就有http头的就不要重试了
                        raise e
                    else:
                        debug(e)
        except Exception as e:
            debug('end _downloadSmallFile fail Exception:')
            debug(e)

    def prepareData(self):
        # 准备路径
        downloadtempPath = self._infos.get('downloadTempPath')
        if not os.path.exists(downloadtempPath):
            os.makedirs(downloadtempPath)

        self._downloadtempPath = downloadtempPath
        #开始下载
        if not self._infos.get('downloadingFiles'):
            fileName = '%s.%s' % (self._infos['fileNameWithoutExt'], self._infos['ext'])
            self._infos['destFileName'] = os.path.join(self._infos.get('downloadDestPath'), fileName)
            downloadFiles = {}
            for i, item in enumerate(self._infos['formats']):
                template = '%d.%s'
                fileName = os.path.join(downloadtempPath, template % (i, item['ext']))
                downloadFiles[fileName] = {'downloadedSize': 0, 'fileSize': item.get('filesize', 0), 'format': item, 'order': i}
            self._infos['downloadingFiles'] = downloadFiles
            self._infos.pop('formats')

            msg = {
                'event': 'download_start',
                'quality': self._infos.get('quality'),
                'data': self._infos
            }

            if self._callback:
                self._callback(msg)

    def fix_dest_filename(self):
        if os.path.exists(self._infos['destFileName']):
            for i in range(100):
                fileName = '%s(%d).%s' % (self._infos['fileNameWithoutExt'], i, self._infos['ext'])
                destfileName = os.path.join(self._infos.get('downloadDestPath'), fileName)
                if not os.path.exists(destfileName) or i == 99:
                    self._infos['destFileName'] = destfileName
                    break

    def move_to_dest(self, source):
        debug('Copy file to dest dir!')
        try:
            self.fix_dest_filename()
            os.chdir(os.path.dirname(source))
            dest = self._infos['destFileName']
            os.rename(source, dest)
            # 拷贝字幕
            if os.path.exists(self._subtitleFile):
                debug('Move Subtitle to Dest Begin...')
                subtitle_ext = os.path.splitext(self._subtitleFile)[1]
                dst_subtitle = os.path.splitext(self._infos['destFileName'])[0] + subtitle_ext
                os.rename(self._subtitleFile, dst_subtitle)
                debug('Move Subtitle to Dest End')
        except Exception as e:
            debug(e)
        try:
            shutil.rmtree(self._infos.get('downloadTempPath'))
        except:
            pass

    def run(self):
        try:
            self.prepareData()
            debug('downloadSubtitle')
            self.downloadSubtitle()
            debug('downloadThumbnailAndIcon')
            self.downloadThumbnailAndIcon(self._infos['fileNameWithoutExt'])
            # YouTube视频下载快于音频10倍，若先下载音频，用户感觉慢，因此给视频提前，感觉上下载快些
            src_medias = sorted(self._infos['downloadingFiles'].iteritems(), key=lambda item: item[1]['order'])
            for key, value in src_medias:
                if self._cancel:
                    raise

                self._downloadingFile = key
                self._download(key, value['format'])
            if self._cancel:
                raise

            # 传与界面，需要原始顺序
            src_files = [item[0] for item in src_medias]
            msg = {
                'event': 'download_complete',
                'sourceFiles': src_files, #文件名
                'destFile': self._infos['destFileName'],
                'nextAction':  self._infos.get('action', 'none'), # 应用层在下载完成之后需要响应的行为包括:"dash_merge(音视频合并), multi_video_merge（多段合并）, convert_to_mp3（转换成mp3）, none(不需要其他附加行为)"
                'thumbnail': self._infos['thumbnail_filename'] if os.path.exists(self._infos['thumbnail_filename']) else ''
            }

            if os.path.exists(self._subtitleFile):
                msg['subtitle'] =  self._subtitleFile,
            debug('------------------download complete-------------------')
            debug(msg)
            debug('------------------download complete-------------------')

            # mac系统，沿用旧逻辑
            if sys.platform != 'win32':
                # 正常结束，不需要额外工作
                if self._infos.get('action', 'none') == 'none':
                    self.move_to_dest(self._infos['downloadingFiles'].keys()[0])
                    msg['destFile'] = self._infos['destFileName']
                elif self._infos.get('action', 'none') in ['dash_convert']:
                    debug('------------------download dash_convert Begin-------------------')
                    self.dash_merge_WEBM()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------download dash_convert End-------------------')
                elif self._infos.get('action', 'none') in ['fixM3u8']:
                    # 先发消息给产品，以更新其界面显示
                    if self._callback:
                        msg['nextAction'] = 'convert_progress'
                        self._callback(msg)
                    debug('------------------FFmpeg fixup m3u8 start-------------------')
                    self.fixup_m3u8()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------FFmpeg fixup m3u8 end-------------------')
            # windows系统，底层处理界面逻辑
            else:
                # 正常结束，不需要额外工作
                if self._infos.get('action', 'none') == 'none':
                    self.move_to_dest(self._infos['downloadingFiles'].keys()[0])
                    msg['destFile'] = self._infos['destFileName']
                elif self._infos.get('action', 'none') in ['dash_convert', 'dash_merge']:
                    # 先发消息给产品，以更新其界面显示
                    if self._callback:
                        msg['nextAction'] = 'merge_progress' if  msg['nextAction'] == 'dash_merge' else 'convert_progress'
                        self._callback(msg)
                    debug('------------------download dash_convert Begin-------------------')
                    self.dash_merge_WEBM()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------download dash_convert End-------------------')
                # 多段视频连接
                elif self._infos.get('action', 'none') in ['multi_video_merge']:
                    # 先发消息给产品，以更新其界面显示
                    if self._callback:
                        msg['nextAction'] = 'merge_progress'
                        self._callback(msg)
                    debug('------------------multi video merge start-------------------')
                    self.multi_video_concat()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------multi video merge end-------------------')
                elif self._infos.get('action', 'none') in ['convert2Mp3']:
                    # 先发消息给产品，以更新其界面显示
                    if self._callback:
                        msg['nextAction'] = 'convert_progress'
                        self._callback(msg)
                    debug('------------------convert to mp3 start-------------------')
                    self.convert_to_mp3()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------convert to mp3 end-------------------')
                elif self._infos.get('action', 'none') in ['fixM3u8']:
                    # 先发消息给产品，以更新其界面显示
                    if self._callback:
                        msg['nextAction'] = 'convert_progress'
                        self._callback(msg)
                    debug('------------------FFmpeg fixup m3u8 start-------------------')
                    self.fixup_m3u8()
                    msg['destFile'] = self._infos['destFileName']
                    msg['nextAction'] = 'none'
                    debug('------------------FFmpeg fixup m3u8 end-------------------')

                # 如果正常结束，即'event'为'None'，windows这一支获取媒体文件信息
                if msg.get('nextAction', 'none') == 'none':
                    debug('------------------get_mediainfo start-------------------')
                    self.get_mediainfo(msg)
                    debug('------------------get_mediainfo end-------------------')

        except:
            if self._cancel:
                msg = {
                    'event': 'download_cancel',
                    'quality': self._infos.get('quality'),
                    'data': self._infos
                }
            else:
                error = traceback.format_exc()
                debug(error)
                msg = {
                    'event': 'download_error',
                    'error': error,
                }
                debug('downloader error!')

        if self._callback:
            self._callback(msg)

    def dash_merge_WEBM(self):
        try:
            from youtube_dl.postprocessor import FFmpegMergerPP
            merger = FFmpegMergerPP(self._ydl)
            info_dict = {}
            for item in self._infos['downloadingFiles'].keys():
                if re.search(r'opus|vorbis|m4a', item):
                    audio = item
                else:
                    video = item
            dest_filename = '%s\youtube_meger%s' % (os.path.dirname(video), os.path.splitext(video)[1])
            info_dict['__files_to_merge'] = [video, audio]
            info_dict['filepath'] = dest_filename
            merger.run(info_dict)
            self.move_to_dest(dest_filename)
            self._GA.send('event', 'dash_merge_WEBM', 'success', '')
        except Exception as e:
            self._GA.send('event', 'dash_merge_WEBM', 'fail', traceback.format_exc())
            debug(traceback.format_exc())

    def multi_video_concat(self):
        try:
            concater = FFmpegConcatMultiVideo(self._ydl, self._infos['quality'])
            info_dict = {}
            # 源文件
            dt = sorted(self._infos['downloadingFiles'].iteritems(), key=lambda item:item[1]['order'])
            src_files = [item[0] for item in dt]
            info_dict['__files_to_concat'] = src_files
            # 目标文件
            dest_filename = '%s\youtube_concat%s' % (self._downloadtempPath, os.path.splitext(self._infos['destFileName'])[1])
            info_dict['destpath'] = dest_filename
            concater.run(info_dict)
            self.move_to_dest(dest_filename)
            self._GA.send('event', 'multi_video_merge', 'success', '')
        except Exception as e:
            self._GA.send('event', 'multi_video_merge', 'fail', traceback.format_exc())
            debug(traceback.format_exc())

    def convert_to_mp3(self):
        try:
            converter = FFmpegExtractMp3(self._ydl, preferredquality=self._infos['quality'])
            info_dict = {}
            # 源文件
            info_dict['filepath'] = self._infos['downloadingFiles'].keys()[0]
            # 目标文件
            dest_filename = '%s\youtube_audio%s' % (self._downloadtempPath, os.path.splitext(self._infos['destFileName'])[1])
            info_dict['destpath'] = dest_filename
            info_dict['filetime'] = self._infos.get('last-modified', None)
            converter.run(info_dict)
            self.move_to_dest(dest_filename)
            self._GA.send('event', 'convert_to_mp3', 'success', '')
        except Exception as e:
            self._GA.send('event', 'convert_to_mp3', 'fail', traceback.format_exc())
            debug(traceback.format_exc())

    def fixup_m3u8(self):
        try:
            converter = FFmpegFixupM3u8PPForToggle(self._ydl)
            info_dict = {}
            # 源文件
            info_dict['filepath'] = self._infos['downloadingFiles'].keys()[0]
            # 目标文件
            dest_filename = '%s\m3u8_fix%s' % (self._downloadtempPath, os.path.splitext(self._infos['destFileName'])[1])
            info_dict['destpath'] = dest_filename
            converter.run(info_dict)
            self.move_to_dest(dest_filename)
            self._GA.send('event', 'fixup_m3u8', 'success', '')
        except Exception as e:
            self._GA.send('event', 'fixup_m3u8', 'fail', traceback.format_exc())
            debug(traceback.format_exc())

    def get_mediainfo(self, msg):
        filename = msg['destFile']
        if not os.path.exists(filename):
            return

        try:
            ffpp = FFmpegPostProcessor(downloader=self._ydl)
            args = [ffpp.executable]
            args += ['-i', filename]
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=get_startinfo())
            stdout, stderr = p.communicate()
            # 获取成功
            if p.returncode != 0:
                stderr = stderr.decode('utf-8', 'replace')
                # 时长
                m = re.search(r'Duration\:\s*((?:\d\d[.:]){3}\d\d)', stderr)
                if m:
                    duration = m.group(1)
                    h, m, s = duration.strip().split(':')
                    msg['duration'] = int(h) * 3600 + int(m) * 60 + float(s)
                # 分辨率
                m = re.search(r'\d{2,}x\d{2,}', stderr)
                if m:
                    msg['resolution'] = m.group()

                # 缩略图
                thumb = msg.get('thumbnail', '')
                if thumb != '' and not os.path.exists(thumb):
                    msg['thumbnail'] = thumb
                    start_pos = random.uniform(5, 20)
                    if msg.get('duration', 0) < start_pos:
                        start_pos = 0;
                    start_pos = str(start_pos);
                    try:
                        args = [ffpp.executable]
                        args += ['-ss', start_pos]
                        args += ['-i', filename]
                        args += ['-f', 'image2']
                        args += ['-y', thumb]
                        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=get_startinfo())
                        p.communicate()
                    except:
                        msg.pop('thumbnail')

            self._GA.send('event', 'get_mediainfo', 'success', '')
        except Exception as e:
            self._GA.send('event', 'get_mediainfo', 'fail', traceback.format_exc())
            debug(traceback.format_exc())


    def delete_tempfiles(self):
        if 'downloadingFiles' in self._infos:
            for item in self._infos['downloadingFiles'].keys():
                try:
                    os.remove(item)
                    tempfile = '%s.part' % item
                    if os.path.exists(tempfile):
                        os.remove(tempfile)
                except:
                    pass

    def cancel(self):
        self._cancel = True

        msg = {
            'event': 'download_cancel',
            'quality': self._infos.get('quality'),
            'data': self._infos
        }
        if self._callback:
            self._callback(msg)


# mp3转换、多段合并。独立抽出来，以避免修改ffmpeg这个文件
import time
import tempfile
import random
import subprocess
if sys.platform == 'win32':
    import win_subprocess
from youtube_dl.postprocessor import FFmpegPostProcessor
from youtube_dl.postprocessor.ffmpeg import (
    FFmpegPostProcessorError,
    get_startinfo,
    FFmpegFixupM3u8PP
)
from youtube_dl.postprocessor.common import AudioConversionError
from youtube_dl.utils import (
    PostProcessingError,
)
from youtube_dl.utilsEX import debug

# 多段合并...ffmpeg在这里不识路径中[【双语・纪实72小时】黄金炸串店_20170303【秋秋】]这样的字符，而[一面湖水]这样的可识，劳动下临时目录，曲线救下国吧！
class FFmpegConcatMultiVideo(FFmpegPostProcessor):
    def __init__(self, downloader=None, quality=0):
        self._quality = quality
        FFmpegPostProcessor.__init__(self, downloader)

    def run(self, information):
        destpath = information['destpath']
        if os.path.exists(destpath):
            os.remove(destpath)
        input_paths = information['__files_to_concat']
        oldest_mtime = min(os.stat(path).st_mtime for path in input_paths)

        # 构建文件列表文件
        input_txtfile = os.path.join(tempfile.gettempdir(), 'input_list.txt')
        if os.path.exists(input_txtfile):
            os.remove(input_txtfile)
        inputf = open(input_txtfile, 'w')
        for i, file in enumerate(input_paths):
            line = 'file \'%s\'' % file
            if i < len(input_paths) - 1:
                line += '\n'
            inputf.writelines(line)
        inputf.close()

        # 构建参数
        args = [self.executable]
        args += ['-f', 'concat']
        #Unsafe file name '/tmp/temp/Watch Naruto Shippuden Season 17
        args += ['-safe', '-1']
        args += ['-i', input_txtfile]
        args += ['-c', 'copy']
        # 置同一磁盘中，rename会很快，如同盘剪切...若是mp3，则需要再转换
        filename, ext = os.path.splitext(destpath)
        is_audio = True if 'mp3' in ext.lower() else False
        if is_audio:
            ext = '.mp4'
        # 若是音频，则置为mp4然后再转
        destpath_new = filename + ext
        args += [destpath_new]

        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, startupinfo=get_startinfo())
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                stderr = stderr.decode('utf-8', 'replace')
                msg = stderr.strip().split('\n')[-1]
                raise FFmpegPostProcessorError(msg)

            # 若是mp3，需要再次转换
            if is_audio:
                converter = FFmpegExtractMp3(self._downloader, preferredquality=self._quality)
                info_dict = {}
                # 源文件
                info_dict['filepath'] = destpath_new
                # 目标文件
                info_dict['destpath'] = destpath
                converter.run(info_dict)
                os.remove(destpath_new)

            self.try_utime(destpath, oldest_mtime, oldest_mtime)
        except Exception as ex:
            debug('multi_video_concat error:')
            debug(ex)
            if is_audio:
                os.remove(destpath_new)
            raise ex
        finally:
            os.remove(input_txtfile)

# 抽取mp3
class FFmpegExtractMp3(FFmpegPostProcessor):
    def __init__(self, downloader=None, preferredquality='320'):
        FFmpegPostProcessor.__init__(self, downloader)
        self._preferredquality = preferredquality

    def run_ffmpeg(self, path, out_path, codec, more_opts):
        if codec is None:
            acodec_opts = []
        else:
            acodec_opts = ['-acodec', codec]
        opts = ['-vn'] + acodec_opts + more_opts
        try:
            FFmpegPostProcessor.run_ffmpeg(self, path, out_path, opts)
        except FFmpegPostProcessorError as err:
            raise AudioConversionError(err.msg)

    def run(self, information):
        src_path = information['filepath']
        acodec = 'libmp3lame'
        extension = 'mp3'
        more_opts = []
        if self._preferredquality is not None:
            if int(self._preferredquality) < 10:
                more_opts += ['-q:a', self._preferredquality]
            else:
                more_opts += ['-b:a', self._preferredquality + 'k']
        dst_path = information['destpath']
        information['ext'] = extension

        # If we download foo.mp3 and convert it to... foo.mp3, then don't delete foo.mp3, silly.
        if dst_path == src_path:
            if self._downloader:
                self._downloader.to_screen('[ffmpeg] Post-process file %s exists, skipping' % dst_path)
            return

        try:
            if self._downloader:
                self._downloader.to_screen('[ffmpeg] Destination: ' + dst_path)
            self.run_ffmpeg(src_path, dst_path, acodec, more_opts)
        except AudioConversionError as e:
            raise PostProcessingError(
                'audio conversion failed: ' + e.msg)
        except Exception as ex:
            raise PostProcessingError('error running ' + self.basename)

        # Try to update the date time for extracted audio file.
        if information.get('filetime') is not None:
            self.try_utime(
                dst_path, time.time(), information['filetime'],
                errnote='Cannot update utime of audio file')


class FFmpegFixupM3u8PPForToggle(FFmpegFixupM3u8PP):
    def get_audio_codec(self, path):
        return 'aac'

    def run(self, info):
        filename = info['filepath']
        if self.get_audio_codec(filename) == 'aac':
            destpath = info['destpath']

            options = ['-c', 'copy', '-f', 'mp4', '-bsf:a', 'aac_adtstoasc']
            self._downloader.to_screen('[ffmpeg] Fixing malformed AAC bitstream in "%s"' % filename)
            self.run_ffmpeg(filename, destpath, options)

            os.remove(filename)
        return [], info
