import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from PIL import Image, ImageTk
import json
import os

class ImageLabeler:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Labeling Tool")
        self.root.geometry("1200x800")
        
        # Variables
        self.image = None
        self.photo = None
        self.scale_factor = 1.0
        self.image_path = None
        self.bounding_boxes = []
        self.current_box = None
        self.start_x = None
        self.start_y = None
        self.selected_box_index = None
        self.selected_box_canvas_id = None
        self.resize_handles = []
        self.resize_mode = None
        self.is_editing_mode = False
        self.class_text_ids = []  # Track text labels on canvas
        self.predefined_classes = ['person', 'vehicle', 'object']  # Default classes
        
        # Create GUI
        self.create_widgets()
        self.create_menu()
        
    def create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open Image", command=self.load_image)
        file_menu.add_separator()
        file_menu.add_command(label="Save Annotations", command=self.save_annotations)
        file_menu.add_command(label="Load Annotations", command=self.load_annotations)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel for controls
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Controls
        ttk.Label(control_frame, text="Controls", font=("Arial", 12, "bold")).pack(pady=(0, 10))
        
        ttk.Button(control_frame, text="Load Image", command=self.load_image).pack(fill=tk.X, pady=2)
        ttk.Button(control_frame, text="Clear All Boxes", command=self.clear_boxes).pack(fill=tk.X, pady=2)
        ttk.Button(control_frame, text="Delete Last Box", command=self.delete_last_box).pack(fill=tk.X, pady=2)
        
        ttk.Separator(control_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # Class name input section
        ttk.Label(control_frame, text="Class Name", font=("Arial", 10, "bold")).pack()
        
        class_frame = ttk.Frame(control_frame)
        class_frame.pack(fill=tk.X, pady=5)
        
        self.class_name_var = tk.StringVar()
        self.class_name_entry = ttk.Entry(class_frame, textvariable=self.class_name_var)
        self.class_name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Button(class_frame, text="Update", command=self.update_selected_class, width=8).pack(side=tk.RIGHT, padx=(5, 0))
        
        ttk.Separator(control_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # Bounding boxes list
        ttk.Label(control_frame, text="Bounding Boxes", font=("Arial", 10, "bold")).pack()
        
        # Frame for listbox and scrollbar
        listbox_frame = ttk.Frame(control_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.bbox_listbox = tk.Listbox(listbox_frame, height=15)
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.bbox_listbox.yview)
        self.bbox_listbox.config(yscrollcommand=scrollbar.set)
        
        self.bbox_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind single click to select box and double click to delete box
        self.bbox_listbox.bind('<Button-1>', self.select_box_from_list)
        self.bbox_listbox.bind('<Double-1>', self.delete_selected_box)
        
        ttk.Separator(control_frame, orient='horizontal').pack(fill=tk.X, pady=10)
        
        # Save/Load buttons
        ttk.Button(control_frame, text="Save Annotations", command=self.save_annotations).pack(fill=tk.X, pady=2)
        ttk.Button(control_frame, text="Load Annotations", command=self.load_annotations).pack(fill=tk.X, pady=2)
        
        # Canvas frame
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Canvas with scrollbars
        self.canvas = tk.Canvas(canvas_frame, bg='gray', cursor='crosshair')
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        
        self.canvas.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack scrollbars and canvas
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind mouse events
        self.canvas.bind('<Button-1>', self.on_canvas_click)
        self.canvas.bind('<B1-Motion>', self.on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_canvas_release)
        self.canvas.bind('<Motion>', self.on_canvas_motion)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Load an image to start labeling")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
    def load_image(self):
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            try:
                self.image_path = file_path
                self.image = Image.open(file_path)
                self.display_image()
                self.clear_boxes()
                self.status_var.set(f"Loaded: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load image: {str(e)}")
                
    def display_image(self):
        if self.image:
            # Calculate scale to fit image in canvas
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            # If canvas dimensions are 1 (not yet rendered), use default
            if canvas_width <= 1 or canvas_height <= 1:
                canvas_width = 800
                canvas_height = 600
            
            img_width, img_height = self.image.size
            
            # Calculate scale factor to fit image in canvas
            scale_x = canvas_width / img_width
            scale_y = canvas_height / img_height
            self.scale_factor = min(scale_x, scale_y, 1.0)  # Don't scale up
            
            # Resize image
            new_width = int(img_width * self.scale_factor)
            new_height = int(img_height * self.scale_factor)
            
            resized_image = self.image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(resized_image)
            
            # Clear canvas and display image
            self.canvas.delete('all')
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
            
            # Update canvas scroll region
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
            
            # Redraw existing bounding boxes
            self.redraw_boxes()
            
    def start_box(self, event):
        if self.photo:
            # Get canvas coordinates
            self.start_x = self.canvas.canvasx(event.x)
            self.start_y = self.canvas.canvasy(event.y)
            
            # Create initial rectangle
            self.current_box = self.canvas.create_rectangle(
                self.start_x, self.start_y, self.start_x, self.start_y,
                outline='red', width=2
            )
            
    def draw_box(self, event):
        if self.current_box and self.photo:
            # Get current canvas coordinates
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)
            
            # Update rectangle
            self.canvas.coords(self.current_box, self.start_x, self.start_y, cur_x, cur_y)
            
    def end_box(self, event):
        if self.current_box and self.photo:
            # Get final coordinates
            end_x = self.canvas.canvasx(event.x)
            end_y = self.canvas.canvasy(event.y)
            
            # Make sure we have a valid box (not just a click)
            if abs(end_x - self.start_x) > 5 and abs(end_y - self.start_y) > 5:
                # Convert to image coordinates
                img_x1 = int(min(self.start_x, end_x) / self.scale_factor)
                img_y1 = int(min(self.start_y, end_y) / self.scale_factor)
                img_x2 = int(max(self.start_x, end_x) / self.scale_factor)
                img_y2 = int(max(self.start_y, end_y) / self.scale_factor)
                
                # Ensure coordinates are within image bounds
                img_width, img_height = self.image.size
                img_x1 = max(0, min(img_x1, img_width))
                img_y1 = max(0, min(img_y1, img_height))
                img_x2 = max(0, min(img_x2, img_width))
                img_y2 = max(0, min(img_y2, img_height))
                
                # Prompt for class name
                class_name = self.prompt_for_class_name()
                if class_name is None:  # User cancelled
                    self.canvas.delete(self.current_box)
                    self.current_box = None
                    return
                
                # Store bounding box
                bbox = {
                    'x1': img_x1,
                    'y1': img_y1,
                    'x2': img_x2,
                    'y2': img_y2,
                    'width': img_x2 - img_x1,
                    'height': img_y2 - img_y1,
                    'class_name': class_name
                }
                
                self.bounding_boxes.append(bbox)
                self.update_bbox_list()
                self.display_image()  # Redraw to show class labels
                self.status_var.set(f"Added bounding box '{class_name}': ({img_x1}, {img_y1}) to ({img_x2}, {img_y2})")
            else:
                # Remove the box if it's too small
                self.canvas.delete(self.current_box)
                
            self.current_box = None
            
    def redraw_boxes(self):
        if not self.photo or not self.bounding_boxes:
            return
            
        for bbox in self.bounding_boxes:
            # Convert image coordinates to canvas coordinates
            x1 = int(bbox['x1'] * self.scale_factor)
            y1 = int(bbox['y1'] * self.scale_factor)
            x2 = int(bbox['x2'] * self.scale_factor)
            y2 = int(bbox['y2'] * self.scale_factor)
            
            self.canvas.create_rectangle(x1, y1, x2, y2, outline='red', width=2)
            
            # Add class name label
            class_name = bbox.get('class_name', 'unlabeled')
            if class_name:
                # Position label at top-left of box with small offset
                text_x = x1 + 3
                text_y = y1 - 15 if y1 > 20 else y1 + 3
                
                # Create background rectangle for text
                self.canvas.create_rectangle(
                    text_x - 2, text_y - 2, 
                    text_x + len(class_name) * 7 + 2, text_y + 12,
                    fill='yellow', outline='black', width=1
                )
                
                # Create text label
                self.canvas.create_text(
                    text_x, text_y,
                    text=class_name,
                    anchor=tk.NW,
                    font=('Arial', 9, 'bold'),
                    fill='black'
                )
            
    def update_bbox_list(self):
        self.bbox_listbox.delete(0, tk.END)
        for i, bbox in enumerate(self.bounding_boxes):
            class_name = bbox.get('class_name', 'unlabeled')
            self.bbox_listbox.insert(tk.END, 
                f"Box {i+1}: [{class_name}] ({bbox['x1']}, {bbox['y1']}) - ({bbox['x2']}, {bbox['y2']})")
            
    def clear_boxes(self):
        self.bounding_boxes = []
        self.update_bbox_list()
        if self.photo:
            self.display_image()  # Redraw image without boxes
        self.status_var.set("Cleared all bounding boxes")
        
    def delete_last_box(self):
        if self.bounding_boxes:
            self.bounding_boxes.pop()
            self.update_bbox_list()
            if self.photo:
                self.display_image()
            self.status_var.set("Deleted last bounding box")
            
    def delete_selected_box(self, event):
        selection = self.bbox_listbox.curselection()
        if selection:
            index = selection[0]
            del self.bounding_boxes[index]
            self.update_bbox_list()
            if self.photo:
                self.display_image()
            self.status_var.set(f"Deleted bounding box {index + 1}")
            
    def save_annotations(self):
        if not self.image_path:
            messagebox.showwarning("Warning", "No image loaded!")
            return
            
        if not self.bounding_boxes:
            messagebox.showwarning("Warning", "No bounding boxes to save!")
            return
            
        # Default save path
        default_name = os.path.splitext(os.path.basename(self.image_path))[0] + "_annotations.json"
        
        file_path = filedialog.asksaveasfilename(
            title="Save Annotations",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                # Create annotation data
                annotation_data = {
                    'image_path': self.image_path,
                    'image_size': {
                        'width': self.image.size[0],
                        'height': self.image.size[1]
                    },
                    'bounding_boxes': self.bounding_boxes
                }
                
                with open(file_path, 'w') as f:
                    json.dump(annotation_data, f, indent=2)
                    
                messagebox.showinfo("Success", f"Annotations saved to {file_path}")
                self.status_var.set(f"Saved {len(self.bounding_boxes)} annotations")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save annotations: {str(e)}")
                
    def load_annotations(self):
        if not self.image_path:
            messagebox.showwarning("Warning", "Load an image first!")
            return
            
        file_path = filedialog.askopenfilename(
            title="Load Annotations",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    annotation_data = json.load(f)
                    
                # Validate the data
                if 'bounding_boxes' in annotation_data:
                    self.bounding_boxes = annotation_data['bounding_boxes']
                    
                    # Add backward compatibility for files without class names
                    for bbox in self.bounding_boxes:
                        if 'class_name' not in bbox:
                            bbox['class_name'] = 'unlabeled'
                    
                    self.update_bbox_list()
                    if self.photo:
                        self.display_image()
                    self.status_var.set(f"Loaded {len(self.bounding_boxes)} annotations")
                    messagebox.showinfo("Success", f"Loaded {len(self.bounding_boxes)} bounding boxes")
                else:
                    messagebox.showerror("Error", "Invalid annotation file format!")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load annotations: {str(e)}")

    def select_box_from_list(self, event):
        """Select a bounding box from the list"""
        selection = self.bbox_listbox.curselection()
        if selection:
            self.selected_box_index = selection[0]
            self.highlight_selected_box()
            # Update class name field with selected box's class name
            bbox = self.bounding_boxes[self.selected_box_index]
            class_name = bbox.get('class_name', 'unlabeled')
            self.class_name_var.set(class_name)
            self.status_var.set(f"Selected Box {self.selected_box_index + 1}")

    def on_canvas_click(self, event):
        """Handle canvas click events"""
        if not self.photo:
            return
            
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        
        # Check if clicking on a resize handle
        handle_clicked = self.check_resize_handle_click(canvas_x, canvas_y)
        if handle_clicked:
            self.resize_mode = handle_clicked
            self.start_x = canvas_x
            self.start_y = canvas_y
            return
            
        # Check if clicking inside an existing box
        clicked_box_index = self.get_box_at_position(canvas_x, canvas_y)
        if clicked_box_index is not None:
            self.selected_box_index = clicked_box_index
            self.highlight_selected_box()
            self.is_editing_mode = True
            self.start_x = canvas_x
            self.start_y = canvas_y
            # Update class name field with selected box's class name
            bbox = self.bounding_boxes[self.selected_box_index]
            class_name = bbox.get('class_name', 'unlabeled')
            self.class_name_var.set(class_name)
            self.status_var.set(f"Selected Box {clicked_box_index + 1} - Drag to move")
            # Update listbox selection
            self.bbox_listbox.selection_clear(0, tk.END)
            self.bbox_listbox.selection_set(clicked_box_index)
            return
            
        # If not clicking on existing box, start creating new box
        self.deselect_box()
        self.start_box(event)

    def on_canvas_drag(self, event):
        """Handle canvas drag events"""
        if not self.photo:
            return
            
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        
        # Handle resize mode
        if self.resize_mode and self.selected_box_index is not None:
            self.resize_selected_box(canvas_x, canvas_y)
            return
            
        # Handle box moving mode
        if self.is_editing_mode and self.selected_box_index is not None:
            self.move_selected_box(canvas_x, canvas_y)
            return
            
        # Handle new box creation
        if self.current_box:
            self.draw_box(event)

    def on_canvas_release(self, event):
        """Handle canvas mouse release events"""
        if not self.photo:
            return
            
        # Handle resize mode
        if self.resize_mode:
            self.finish_resize()
            return
            
        # Handle box moving mode
        if self.is_editing_mode:
            self.finish_move()
            return
            
        # Handle new box creation
        if self.current_box:
            self.end_box(event)

    def on_canvas_motion(self, event):
        """Handle canvas mouse motion for cursor changes"""
        if not self.photo:
            return
            
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        
        # Check if hovering over resize handle
        if self.selected_box_index is not None:
            handle = self.check_resize_handle_click(canvas_x, canvas_y)
            if handle:
                if handle in ['nw', 'se']:
                    self.canvas.config(cursor='size_nw_se')
                elif handle in ['ne', 'sw']:
                    self.canvas.config(cursor='size_ne_sw')
                elif handle in ['n', 's']:
                    self.canvas.config(cursor='size_ns')
                elif handle in ['e', 'w']:
                    self.canvas.config(cursor='size_we')
                return
                
        # Check if hovering over existing box
        clicked_box_index = self.get_box_at_position(canvas_x, canvas_y)
        if clicked_box_index is not None:
            self.canvas.config(cursor='hand2')
        else:
            self.canvas.config(cursor='crosshair')

    def get_box_at_position(self, canvas_x, canvas_y):
        """Check if position is inside any bounding box"""
        for i, bbox in enumerate(self.bounding_boxes):
            x1 = bbox['x1'] * self.scale_factor
            y1 = bbox['y1'] * self.scale_factor
            x2 = bbox['x2'] * self.scale_factor
            y2 = bbox['y2'] * self.scale_factor
            
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                return i
        return None

    def highlight_selected_box(self):
        """Highlight the selected bounding box"""
        if self.selected_box_index is None:
            return
            
        self.display_image()  # Redraw all boxes
        
        # Highlight selected box
        bbox = self.bounding_boxes[self.selected_box_index]
        x1 = int(bbox['x1'] * self.scale_factor)
        y1 = int(bbox['y1'] * self.scale_factor)
        x2 = int(bbox['x2'] * self.scale_factor)
        y2 = int(bbox['y2'] * self.scale_factor)
        
        self.selected_box_canvas_id = self.canvas.create_rectangle(
            x1, y1, x2, y2, outline='blue', width=3
        )
        
        # Add resize handles
        self.add_resize_handles(x1, y1, x2, y2)

    def add_resize_handles(self, x1, y1, x2, y2):
        """Add resize handles to the selected box"""
        self.resize_handles = []
        handle_size = 6
        
        # Corner handles
        handles = [
            ('nw', x1, y1),
            ('ne', x2, y1), 
            ('se', x2, y2),
            ('sw', x1, y2),
            # Edge handles
            ('n', (x1 + x2) // 2, y1),
            ('s', (x1 + x2) // 2, y2),
            ('e', x2, (y1 + y2) // 2),
            ('w', x1, (y1 + y2) // 2)
        ]
        
        for handle_type, hx, hy in handles:
            handle_id = self.canvas.create_rectangle(
                hx - handle_size//2, hy - handle_size//2,
                hx + handle_size//2, hy + handle_size//2,
                fill='blue', outline='white', width=1
            )
            self.resize_handles.append((handle_type, handle_id, hx, hy))

    def check_resize_handle_click(self, canvas_x, canvas_y):
        """Check if click is on a resize handle"""
        for handle_type, handle_id, hx, hy in self.resize_handles:
            if abs(canvas_x - hx) <= 6 and abs(canvas_y - hy) <= 6:
                return handle_type
        return None

    def resize_selected_box(self, canvas_x, canvas_y):
        """Resize the selected box based on handle movement"""
        if self.selected_box_index is None or not self.resize_mode:
            return
            
        bbox = self.bounding_boxes[self.selected_box_index]
        
        # Convert current coordinates to image coordinates
        img_x = canvas_x / self.scale_factor
        img_y = canvas_y / self.scale_factor
        
        # Update bounding box based on resize mode
        if 'n' in self.resize_mode:
            bbox['y1'] = max(0, min(img_y, bbox['y2'] - 5))
        if 's' in self.resize_mode:
            bbox['y2'] = min(self.image.size[1], max(img_y, bbox['y1'] + 5))
        if 'w' in self.resize_mode:
            bbox['x1'] = max(0, min(img_x, bbox['x2'] - 5))
        if 'e' in self.resize_mode:
            bbox['x2'] = min(self.image.size[0], max(img_x, bbox['x1'] + 5))
            
        # Update width and height
        bbox['width'] = bbox['x2'] - bbox['x1']
        bbox['height'] = bbox['y2'] - bbox['y1']
        
        # Update display
        self.highlight_selected_box()
        self.update_bbox_list()

    def move_selected_box(self, canvas_x, canvas_y):
        """Move the selected box"""
        if self.selected_box_index is None:
            return
            
        # Calculate movement delta
        dx = (canvas_x - self.start_x) / self.scale_factor
        dy = (canvas_y - self.start_y) / self.scale_factor
        
        bbox = self.bounding_boxes[self.selected_box_index]
        
        # Calculate new position
        new_x1 = bbox['x1'] + dx
        new_y1 = bbox['y1'] + dy
        new_x2 = bbox['x2'] + dx
        new_y2 = bbox['y2'] + dy
        
        # Ensure box stays within image bounds
        img_width, img_height = self.image.size
        if new_x1 >= 0 and new_x2 <= img_width and new_y1 >= 0 and new_y2 <= img_height:
            bbox['x1'] = new_x1
            bbox['y1'] = new_y1 
            bbox['x2'] = new_x2
            bbox['y2'] = new_y2
            
            self.start_x = canvas_x
            self.start_y = canvas_y
            
            # Update display
            self.highlight_selected_box()
            self.update_bbox_list()

    def finish_resize(self):
        """Finish resizing operation"""
        self.resize_mode = None
        if self.selected_box_index is not None:
            bbox = self.bounding_boxes[self.selected_box_index]
            self.status_var.set(f"Resized Box {self.selected_box_index + 1}: ({int(bbox['x1'])}, {int(bbox['y1'])}) to ({int(bbox['x2'])}, {int(bbox['y2'])})")

    def finish_move(self):
        """Finish moving operation"""
        self.is_editing_mode = False
        if self.selected_box_index is not None:
            bbox = self.bounding_boxes[self.selected_box_index]
            self.status_var.set(f"Moved Box {self.selected_box_index + 1}: ({int(bbox['x1'])}, {int(bbox['y1'])}) to ({int(bbox['x2'])}, {int(bbox['y2'])})")

    def deselect_box(self):
        """Deselect the currently selected box"""
        self.selected_box_index = None
        self.selected_box_canvas_id = None
        self.resize_handles = []
        self.resize_mode = None
        self.is_editing_mode = False
        self.bbox_listbox.selection_clear(0, tk.END)
        self.class_name_var.set("")  # Clear class name field
        if self.photo:
            self.display_image()

    def prompt_for_class_name(self):
        """Prompt user for class name using a dialog with predefined classes"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Class Name")
        dialog.geometry("350x180")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center the dialog
        dialog.geometry("+%d+%d" % (self.root.winfo_rootx() + 50, self.root.winfo_rooty() + 50))
        
        result = [None]
        
        # Create widgets
        ttk.Label(dialog, text="Select or enter class name for this bounding box:").pack(pady=10)
        
        # Combobox with predefined classes
        class_var = tk.StringVar()
        class_combo = ttk.Combobox(dialog, textvariable=class_var, width=30)
        class_combo['values'] = self.predefined_classes
        class_combo.pack(pady=5)
        class_combo.focus()
        
        # Set first class as default if available
        if self.predefined_classes:
            class_combo.set(self.predefined_classes[0])
        
        def ok_pressed():
            selected_class = class_var.get().strip()
            if selected_class:
                # Add to predefined classes if it's new
                if selected_class not in self.predefined_classes:
                    self.predefined_classes.append(selected_class)
                result[0] = selected_class
            dialog.destroy()
            
        def cancel_pressed():
            result[0] = None
            dialog.destroy()
        
        # Button frame
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="OK", command=ok_pressed).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=cancel_pressed).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Manage Classes", command=lambda: self.manage_classes_dialog(dialog)).pack(side=tk.LEFT, padx=5)
        
        # Bind Enter key to OK
        class_combo.bind('<Return>', lambda e: ok_pressed())
        dialog.bind('<Escape>', lambda e: cancel_pressed())
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result[0] if result[0] else "unlabeled"

    def update_selected_class(self):
        """Update the class name of the currently selected bounding box"""
        if self.selected_box_index is not None:
            new_class_name = self.class_name_var.get().strip()
            if new_class_name:
                self.bounding_boxes[self.selected_box_index]['class_name'] = new_class_name
                self.update_bbox_list()
                self.display_image()  # Redraw to update class labels
                self.status_var.set(f"Updated class name to '{new_class_name}'")
            else:
                messagebox.showwarning("Warning", "Please enter a class name")
        else:
            messagebox.showwarning("Warning", "Please select a bounding box first")

    def manage_classes_dialog(self, parent_dialog):
        """Dialog to manage predefined classes"""
        manage_dialog = tk.Toplevel(parent_dialog)
        manage_dialog.title("Manage Classes")
        manage_dialog.geometry("300x350")
        manage_dialog.transient(parent_dialog)
        manage_dialog.grab_set()
        
        # Center the dialog
        manage_dialog.geometry("+%d+%d" % (parent_dialog.winfo_rootx() + 25, parent_dialog.winfo_rooty() + 25))
        
        # Create widgets
        ttk.Label(manage_dialog, text="Manage Predefined Classes", font=("Arial", 12, "bold")).pack(pady=10)
        
        # Frame for class list and scrollbar
        list_frame = ttk.Frame(manage_dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        class_listbox = tk.Listbox(list_frame)
        class_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=class_listbox.yview)
        class_listbox.config(yscrollcommand=class_scrollbar.set)
        
        class_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        class_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate listbox
        def refresh_list():
            class_listbox.delete(0, tk.END)
            for class_name in self.predefined_classes:
                class_listbox.insert(tk.END, class_name)
        
        refresh_list()
        
        # Entry for new class
        entry_frame = ttk.Frame(manage_dialog)
        entry_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(entry_frame, text="New Class:").pack(side=tk.LEFT)
        new_class_var = tk.StringVar()
        new_class_entry = ttk.Entry(entry_frame, textvariable=new_class_var)
        new_class_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        # Button functions
        def add_class():
            new_class = new_class_var.get().strip()
            if new_class and new_class not in self.predefined_classes:
                self.predefined_classes.append(new_class)
                refresh_list()
                new_class_var.set("")
                class_listbox.selection_clear(0, tk.END)
                class_listbox.selection_set(tk.END)
            elif new_class in self.predefined_classes:
                messagebox.showwarning("Warning", "Class already exists!")
        
        def remove_class():
            selection = class_listbox.curselection()
            if selection:
                index = selection[0]
                class_name = self.predefined_classes[index]
                if messagebox.askyesno("Confirm", f"Remove class '{class_name}'?"):
                    del self.predefined_classes[index]
                    refresh_list()
        
        def edit_class():
            selection = class_listbox.curselection()
            if selection:
                index = selection[0]
                old_name = self.predefined_classes[index]
                new_name = tk.simpledialog.askstring("Edit Class", f"Edit class name:", initialvalue=old_name)
                if new_name and new_name.strip():
                    new_name = new_name.strip()
                    if new_name != old_name:
                        if new_name not in self.predefined_classes:
                            self.predefined_classes[index] = new_name
                            refresh_list()
                            class_listbox.selection_clear(0, tk.END)
                            class_listbox.selection_set(index)
                        else:
                            messagebox.showwarning("Warning", "Class already exists!")
        
        # Buttons
        button_frame = ttk.Frame(manage_dialog)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(button_frame, text="Add", command=add_class).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Remove", command=remove_class).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Edit", command=edit_class).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(button_frame, text="Close", command=manage_dialog.destroy).pack(side=tk.RIGHT, padx=2)
        
        # Bind Enter key to add class
        new_class_entry.bind('<Return>', lambda e: add_class())
        
        # Bind double-click to edit
        class_listbox.bind('<Double-1>', lambda e: edit_class())

def main():
    root = tk.Tk()
    app = ImageLabeler(root)
    root.mainloop()

if __name__ == "__main__":
    main()
