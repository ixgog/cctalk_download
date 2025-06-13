@echo off
echo 此脚本用于将ui文件夹下的ui文件转为py文件
set /p uiFile=输入ui文件夹的ui文件名，不带后缀:
pyuic5 -o ui\%uiFile%.py ui\%uiFile%.ui