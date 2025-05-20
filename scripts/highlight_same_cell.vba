Option Explicit

' 使用Range对象跟踪高亮的单元格
Private highlightedCells As Range

Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    ' 先清除已有高亮
    If Not highlightedCells Is Nothing Then
        RemoveHighlights
    End If

    ' 如果只选择了一个单元格
    If Target.Cells.Count = 1 And Not IsEmpty(Target) Then
        Dim stockName As String
        stockName = ExtractStockName(Target.Value)

        ' 确保提取的名称不为空
        If Len(stockName) > 0 Then
            ' 找到并高亮匹配的单元格
            FindAndHighlightCells stockName
        End If
    End If
End Sub

Private Function ExtractStockName(text As String) As String
    ' 移除末尾的数字
    Dim result As String
    result = text

    ' 从末尾开始，移除所有数字
    Do While Len(result) > 0 And IsNumeric(Right(result, 1))
        result = Left(result, Len(result) - 1)
    Loop

    ExtractStockName = result
End Function

Private Sub RemoveHighlights()
    ' 只清除已高亮单元格的边框
    On Error Resume Next
    highlightedCells.BorderAround LineStyle:=xlContinuous, Weight:=xlThin, ColorIndex:=xlAutomatic
    On Error GoTo 0

    ' 重置高亮单元格集合
    Set highlightedCells = Nothing
End Sub

Private Sub FindAndHighlightCells(stockName As String)
    ' 使用Find方法查找匹配的单元格
    Dim searchRange As Range
    Set searchRange = ActiveSheet.UsedRange

    Dim firstCell As Range
    Dim currentCell As Range
    Dim foundCell As Range

    ' 设置查找条件
    With searchRange
        Set foundCell = .Find(What:=stockName, _
                            LookIn:=xlValues, _
                            LookAt:=xlPart, _
                            SearchOrder:=xlByRows, _
                            SearchDirection:=xlNext)

        If Not foundCell Is Nothing Then
            ' 记住第一个找到的单元格
            Set firstCell = foundCell

            ' 设置初始高亮单元格
            Set highlightedCells = foundCell

            ' 继续查找剩余匹配项
            Do
                ' 高亮当前单元格
                foundCell.BorderAround LineStyle:=xlContinuous, Weight:=xlThick, ColorIndex:=5

                ' 查找下一个匹配项
                Set foundCell = .FindNext(foundCell)

                ' 如果找到新单元格且不是第一个，添加到高亮集合
                If Not foundCell Is Nothing Then
                    If foundCell.Address <> firstCell.Address Then
                        ' 添加到高亮单元格
                        If highlightedCells Is Nothing Then
                            Set highlightedCells = foundCell
                        Else
                            Set highlightedCells = Union(highlightedCells, foundCell)
                        End If
                    Else
                        ' 回到第一个单元格，搜索完成
                        Exit Do
                    End If
                Else
                    Exit Do
                End If
            Loop
        End If
    End With
End Sub