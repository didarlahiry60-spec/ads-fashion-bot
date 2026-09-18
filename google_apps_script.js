function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    
    var headers = [
      "Date & Time",
      "Order ID", 
      "Customer Name", 
      "Phone Number", 
      "Address", 
      "Zone", 
      "Items & Size", 
      "Total (BDT)", 
      "Payment Method", 
      "Status"
    ];
    
    function getOrCreateSheet(sheetName, color) {
      var sheet = ss.getSheetByName(sheetName);
      if (!sheet) {
        sheet = ss.insertSheet(sheetName);
      }
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(headers);
        var headerRange = sheet.getRange(1, 1, 1, headers.length);
        headerRange.setFontWeight("bold");
        headerRange.setBackground(color || "#1f2937");
        headerRange.setFontColor("#ffffff");
        sheet.setFrozenRows(1);
      }
      return sheet;
    }
    
    var rowData = [
      data.date_time || new Date().toLocaleString("en-US", {timeZone: "Asia/Dhaka"}),
      data.order_id,
      data.customer_name,
      "'" + data.customer_phone, // Force text format for phone
      data.shipping_address,
      data.zone,
      data.items,
      data.total_price,
      data.payment_method,
      data.status || "Pending"
    ];
    
    // 1. All Orders Sheet
    var allSheet = getOrCreateSheet("All Orders", "#1e3a8a");
    allSheet.appendRow(rowData);
    
    // 2. Zone Specific Sheet
    if (data.zone === "Inside Dhaka" || (data.zone && data.zone.indexOf("Inside") !== -1)) {
      var inSheet = getOrCreateSheet("Inside Dhaka", "#065f46");
      inSheet.appendRow(rowData);
    } else {
      var outSheet = getOrCreateSheet("Outside Dhaka", "#92400e");
      outSheet.appendRow(rowData);
    }
    
    return ContentService.createTextOutput(JSON.stringify({"status": "success", "order_id": data.order_id}))
      .setMimeType(ContentService.MimeType.JSON);
      
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({"status": "error", "message": error.toString()}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
