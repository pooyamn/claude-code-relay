# Read-only counterpart of Ledger.ResumeSuperseded/MenuSuperseded. A proof
# removes a stale lifecycle fence; it never confirms, edits or retries the old
# operation. Model actions and unmatched or malformed receipts still block.
function Get-TopicReceiptSupersession {
 param([string]$Operation,[string]$Kind,[string]$Payload,[scriptblock]$Read)
 if($Operation -cnotmatch '^[a-f0-9]{32}$' -or $Kind -notin @('native/thread/resume','telegram/setMyCommands')){return}
 try{
  $value=$Payload|ConvertFrom-Json
  if($Kind -eq 'native/thread/resume'){
   $parameters=$value.parameters
   $allowed=@('threadId','cwd','excludeTurns','approvalPolicy','approvalsReviewer','permissions')
   $names=@($parameters.PSObject.Properties.Name)
   if($names.Count -ne $allowed.Count -or @($names|Where-Object {$_ -cnotin $allowed}).Count -or
    $parameters.excludeTurns -isnot [bool] -or -not $parameters.excludeTurns){return}
   foreach($name in $allowed|Where-Object {$_ -ne 'excludeTurns'}){if($parameters.$name -isnot [string]){return}}
   $uuid=[Guid]::Empty
   if(-not [Guid]::TryParseExact($parameters.threadId,'D',[ref]$uuid) -or [string]::IsNullOrWhiteSpace($parameters.cwd)){return}
   $sql="SELECT n.id,n.result FROM operations n JOIN operations o ON o.id='$Operation' WHERE n.rowid>o.rowid AND n.kind='native/thread/resume' AND n.status='confirmed' AND json_extract(n.payload,'$.parameters')=json_extract(o.payload,'$.parameters') ORDER BY n.rowid DESC"
   $rows=& $Read $sql
   foreach($row in $rows){
    $ack=$row[1]|ConvertFrom-Json
    if($ack.thread.id -ceq $parameters.threadId -and $ack.thread.cwd -ceq $parameters.cwd -and
     $ack.approvalPolicy -is [string] -and $ack.approvalPolicy -ceq $parameters.approvalPolicy){
     return @{operation=$Operation;kind=$Kind;supersededBy=$row[0];reason='identical-later-attachment-ack';originalRetained=$true;replayed=$false}
    }
   }
  }else{
   $names=@($value.PSObject.Properties.Name);$scope=$value.scope;$scopeNames=@($scope.PSObject.Properties.Name)
   if($names.Count -ne 2 -or @($names|Where-Object {$_ -cnotin @('scope','commands')}).Count -or
    $value.commands -isnot [array] -or $scopeNames.Count -ne 3 -or
    @($scopeNames|Where-Object {$_ -cnotin @('type','chat_id','user_id')}).Count -or
    $scope.type -cne 'chat_member' -or ($scope.chat_id -isnot [long] -and $scope.chat_id -isnot [int]) -or
    ($scope.user_id -isnot [long] -and $scope.user_id -isnot [int]) -or $scope.chat_id -ge 0 -or $scope.user_id -le 0){return}
   $sql="SELECT n.id,n.result FROM operations n JOIN operations o ON o.id='$Operation' WHERE n.rowid>o.rowid AND n.kind='telegram/setMyCommands' AND n.status='confirmed' AND n.payload=o.payload AND n.result='true' ORDER BY n.rowid DESC LIMIT 1"
   $rows=& $Read $sql
   if($rows.Length -eq 1){return @{operation=$Operation;kind=$Kind;supersededBy=$rows[0][0];reason='identical-later-menu-ack';originalRetained=$true;replayed=$false}}
  }
 }catch{Write-Verbose ("$_ " + $_.ScriptStackTrace);return} # Malformed or unproved evidence is blocking, never a waiver.
}
