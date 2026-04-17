@echo off
chcp 65001 >nul
echo ==========================================
echo      批量转换 Excel 到规则数据
echo ==========================================
echo.
echo 当前支持:
echo   - 项目特征 Sheet: 名称 ^| CODE ^| 下拉
echo   - 计算项目 Sheet: 名称 ^| CODE ^| 单位
echo   - 属性 Sheet: 名称 ^| CODE ^| 属性值
echo   - 同时兼容旧版 属性/计算项目/核心项目 结构
echo.
echo 默认会优先读取项目目录下的 ^"data\input\component_type_attribute_excels^" 目录
echo 如需指定目录，请执行:
echo   python batch_convert.py 目录路径
echo.

python batch_convert.py %*

echo.
pause
