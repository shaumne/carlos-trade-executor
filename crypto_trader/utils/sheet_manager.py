def clean_coin_line(self, row_index):
        """Clean up a coin line after successful sell by resetting relevant fields"""
        try:
            # Fields to reset
            updates = {
                'Buy Signal': 'WAIT',
                'Order Placed?': '',
                'Order Date': '',
                'Purchase Price': '',
                'Quantity': '',
                'Take Profit': '',
                'Stop-Loss': '',
                'Purchase Date': '',
                'Sold?': '',
                'Sell Price': '',
                'Sell Quantity': '',
                'Sold Date': '',
                'Notes': '',
                'order_id': ''
            }
            
            # Set Tradable back to YES
            try:
                self.worksheet.update_cell(row_index, self.get_column_index_by_name('Tradable'), 'YES')
            except Exception as e:
                logger.error(f"Error updating Tradable column: {str(e)}")
            
            # Update all other fields
            for field, value in updates.items():
                try:
                    col_index = self.get_column_index_by_name(field)
                    self.worksheet.update_cell(row_index, col_index, value)
                except Exception as e:
                    logger.error(f"Error updating {field} column: {str(e)}")
            
            logger.info(f"Successfully cleaned up coin line at row {row_index}")
            return True
            
        except Exception as e:
            logger.error(f"Error cleaning coin line at row {row_index}: {str(e)}")
            return False 