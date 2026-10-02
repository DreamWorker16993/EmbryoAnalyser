/*
Working Principal:
1. create two separate graphs, one with only BOUNADRIES, one with only CENTROIDS
2. on centroid graph, enlarge every cell boundary to encircle sufficient neighbouring centroids
3. draw a line from the selected centroid to a neighbouring centroid. If it passes the boundary only once, then it's a neighbour

REMARK: compared to purely encircling and selecting, 
		this method is more accurate (fails when cell shapes are severely irregular) 
		but more time-consuming (O(mn) for one image)
*/

// weirdly, not using batch mode is much faster


//main
masterDir = getDirectory("Choose the Master Directory containing subfolders:");  //master directory containing all subfolders

setBatchMode(false); 

processFolder(masterDir);

print("--- ALL SUBFOLDERS FULLY PROCESSED ---");


// ==========================================
// RECURSIVE DIRECTORY SCANNER
// ==========================================
function processFolder(currentDir) {
    list = getFileList(currentDir);
    
    // First, check if there are images in this specific folder to process
    imageFile = "";
    roiFile = "";
    
    for (i = 0; i < list.length; i++) {
        // If we find a subdirectory, recursively call this function to go deeper
        if (File.isDirectory(currentDir + list[i])) {
            processFolder(currentDir + list[i]);
        }
        
        // Identify the raw image tif file in the current folder
        if (endsWith(toLowerCase(list[i]), ".tif")) {
            imageFile = list[i];
        }
        
        // Identify the corresponding ROI zip file
        if (endsWith(toLowerCase(list[i]), ".zip")) {
            roiFile = list[i];
        }
    }
    
    // If we have an image and an ROI file in this folder, process them!
    if (imageFile != "" && roiFile != "") {
        processTissue(currentDir, imageFile, roiFile);
    }
}

function processTissue(dir, imgName, roiName) {
    //print("Processing: " + dir + imgName);
    
    // Clean up anything open in the ROI manager from previous runs
    if (roiManager("count") > 0) {
        roiManager("reset");
    }
    
    // Open the Image and corresponding ROI set
    open(dir + imgName);
    roiManager("Open", dir + roiName);
    
	    
	Image.removeScale;
	roiManager("deselect");
	//main_img = getTitle();
	
	W = getWidth();
	H = getHeight();
	
	//create separate centroid and boundary graphs
	newImage("boundary_graph", "16-bit black", W, H, 1); //width, height, depth
	newImage("centroid_graph", "16-bit black", W, H, 1);
	
	
	//draw boundary onto boundary graph. binarise and skeletonise
	selectWindow("boundary_graph");
	roiManager("Show All");
	//setOption("BlackBackground", false);
	
	// USE these lines if graph creation goes wrong
	setForegroundColor(255, 255, 255);
	setBackgroundColor(0, 0, 0);
	roiManager("Draw");
	run("Convert to Mask");
	run("Skeletonize");
	
	
	//draw centroids onto centroid graph
	count = roiManager("count");
	run("Set Measurements...", "centroid redirect=imgName decimal=0");
	roiManager("measure"); 
	Table.rename("Results", "all_centroids");  //prevent Results table clash in later code
	
	selectWindow("centroid_graph");
	setColor("white");
	setLineWidth(1);
	for (k = 0; k < count; k++) {
	    //roiManager("select", k);
	    draw_centroid(k);
	}
	
	function draw_centroid(idx){
		// get centroid coordinates
	    selectWindow("all_centroids");
	    x = Table.get("X", idx);
	    y = Table.get("Y", idx);
	    
	    // Draw a cross at (X, Y)
	    drawLine(x - 2, y, x + 2, y); // Horizontal bar
	    drawLine(x, y - 2, x, y + 2); // Vertical bar
	}
	
	
	// -------------------------- NOW STARTS NEIGHBOURING-COUNTING -------------------------------
	// save header
	csv_path = dir + "slow_neighbour_counting.csv";
	header = "index,X,Y,n_neighbours,distances\n"; // data will be saved in this format
	File.saveString(header, csv_path);
	
	//selectWindow("centroid_graph");
	thres = 5;
	
	// iterate through all centroids
	for (i = 0; i < count; i++) {
		//get centroid coordinates of the central cell
		selectWindow("all_centroids");
		x_ctr = round(Table.get("X", i));
		y_ctr = round(Table.get("Y", i));
		
		// get the bounding rectangle of cell
		roiManager("Select", i);
		Roi.getBounds(x, y, w, h); 
		
		// verify the rectangle is not at the boundaries
		if ((x > thres) && (y > thres) && (x + w < W - thres) && (y + h < H - thres)){
			selectWindow("centroid_graph"); //new adjustment
			roiManager("Select", i);
			encircle();
			half_line = count_neighbours();
			
			// every line must be a string, separated by ","
			// starts with "" so result is str
			csv_line = "" + i + "," + x_ctr + "," + y_ctr + "," + half_line;
			File.append(csv_line, csv_path);
		}
	}
	
	
	selectWindow("all_centroids");
	run("Close");
	selectWindow("Results");
	run("Close");
	/*
	selectWindow("boundary_graph");
	run("Close");
	selectWindow("centroid_graph");
	run("Close");
	
	selectWindow(imgName);
	run("Close");
	selectWindow(roiName);
	run("Close");
	*/
	close("*");
	
	//print("--- Neighbour Counting Completed ---");
	
	
	function encircle(){
		// scale removed, enlargement in pixel
		// larger enlarge, higher accuracy but longer runtime
		run("Enlarge...", "enlarge=30");  
	
		// the whole image is black, only the centroids are cyan/white
		// therefore prominence = 0 works well
		// now Results table contains candidate neighbour centroids
		run("Find Maxima...", "prominence=0 output=List");
	}
	
	function count_neighbours(){
		n_nbr = 0;
		local_dist_array = newArray(0); //distances to all neighbours
		
		for (j = 0; j < nResults; j++){
			// neighbour coordinates
			x_nbr = getResult("X", j);
			y_nbr = getResult("Y", j);
			
			// exclude the central cell itself
			if ((x_ctr != x_nbr) || (y_ctr != y_nbr)){
				// connect two centroids
				selectWindow("boundary_graph");
				setTool("polyline");
				makeLine(x_ctr, y_ctr, x_nbr, y_nbr); 	
				
				setOption("InterpolateLines", false);  //otherwise float grey scale
				run("Plots...", "width=600 height=340 font=14 draw_ticks minimum=0 maximum=0 vertical");
				profile = getProfile(); //colour profile of the line. white: 0, black: 255
				
				n_boundary = 0;
	
				// count num of boundaries it passes
				for (p = 0; p < profile.length; p++) {
					if (profile[p] == 255) {
						n_boundary++;
					}
				}
				
				// if is a neighbour, update n_nbr and local_distance_array
				// ADJUSTMENT: <=
				if (n_boundary <= 1){
					n_nbr++;
					d = sqrt(Math.pow(x_ctr - x_nbr, 2) + Math.pow(y_ctr - y_nbr, 2));
					local_dist_array = Array.concat(local_dist_array, d);
				}
			}
		}	
		dist_str = String.join(local_dist_array, ",");	
		return "" + n_nbr + ",\"" + dist_str + "\"\n";
	}
}
	
	    
    